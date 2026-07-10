from datetime import datetime, timezone

from app.core.exceptions import ForbiddenException, NotFoundException
from app.database.mongodb import get_collection
from app.templates.model import build_template_document
from app.templates.schema import TemplateCreate, TemplateUpdate
from app.schemas.common import PaginationParams
from app.utils.pagination import build_paginated_response
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "templates"


async def create_template(employee_id: str, is_admin: bool, payload: TemplateCreate) -> dict:
    # Only admins can create global templates
    if payload.isGlobal and not is_admin:
        raise ForbiddenException("Only admins can create global templates")

    doc = build_template_document(
        employee_id=employee_id,
        name=payload.name,
        subject=payload.subject,
        body=payload.body,
        signature=payload.signature,
        tags=payload.tags,
        is_global=payload.isGlobal,
    )
    col = get_collection(COLLECTION)
    result = await col.insert_one(doc)
    created = await col.find_one({"_id": result.inserted_id})
    return serialize_doc(created)


async def list_templates(
    employee_id: str,
    is_admin: bool,
    params: PaginationParams,
    tag: str | None = None,
    search: str | None = None,
) -> dict:
    col = get_collection(COLLECTION)

    # Employees see their own templates + all global ones
    # Admins see everything
    if is_admin:
        query: dict = {}
    else:
        query = {"$or": [{"employeeId": employee_id}, {"isGlobal": True}]}

    if tag:
        query["tags"] = tag
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"subject": {"$regex": search, "$options": "i"}},
        ]

    total = await col.count_documents(query)
    cursor = col.find(query).sort("createdAt", -1).skip(params.skip).limit(params.pageSize)
    docs = serialize_list([d async for d in cursor])
    return build_paginated_response(docs, total, params)


async def get_template(template_id: str, employee_id: str, is_admin: bool) -> dict:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(template_id)})
    if not doc:
        raise NotFoundException("Template not found")
    # Employees can read global templates or their own
    if not is_admin and not doc.get("isGlobal") and doc.get("employeeId") != employee_id:
        raise ForbiddenException("Access denied")
    return serialize_doc(doc)


async def update_template(
    template_id: str, employee_id: str, is_admin: bool, payload: TemplateUpdate
) -> dict:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(template_id)})
    if not doc:
        raise NotFoundException("Template not found")
    # Only owner or admin can update
    if not is_admin and doc.get("employeeId") != employee_id:
        raise ForbiddenException("You can only edit your own templates")
    # Employees cannot promote a template to global
    if payload.isGlobal and not is_admin:
        raise ForbiddenException("Only admins can make a template global")

    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        return serialize_doc(doc)

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await col.find_one_and_update(
        {"_id": to_object_id(template_id)},
        {"$set": update_data},
        return_document=True,
    )
    return serialize_doc(result)


async def delete_template(template_id: str, employee_id: str, is_admin: bool) -> None:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(template_id)})
    if not doc:
        raise NotFoundException("Template not found")
    if not is_admin and doc.get("employeeId") != employee_id:
        raise ForbiddenException("You can only delete your own templates")
    await col.delete_one({"_id": to_object_id(template_id)})


async def increment_usage(template_id: str) -> None:
    """Called by the campaign engine each time a template is used."""
    col = get_collection(COLLECTION)
    await col.update_one(
        {"_id": to_object_id(template_id)},
        {"$inc": {"usageCount": 1}, "$set": {"updatedAt": datetime.now(timezone.utc)}},
    )


async def preview_template(template_id: str, employee_id: str, is_admin: bool, sample_lead: dict) -> dict:
    """
    Resolve placeholders against a sample lead and return the rendered
    subject + body without sending anything.
    """
    template = await get_template(template_id, employee_id, is_admin)
    subject = _replace_placeholders(template["subject"], sample_lead)
    body = _replace_placeholders(template["body"], sample_lead)
    return {"subject": subject, "body": body, "signature": template["signature"]}


def _replace_placeholders(text: str, lead: dict) -> str:
    """Simple [placeholder] substitution used for preview and plain-text personalization."""
    replacements = {
        "[name]": lead.get("fullName") or lead.get("name") or "there",
        "[company]": lead.get("company", "your company"),
        "[industry]": lead.get("industry", "your industry"),
        "[designation]": lead.get("designation", ""),
        "[country]": lead.get("country", ""),
        "[domain]": lead.get("domain", ""),
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value.strip() if isinstance(value, str) else value)
    return text
