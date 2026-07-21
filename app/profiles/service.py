from datetime import datetime, timezone
import logging

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.database.mongodb import get_collection
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.profiles.model import MAX_PROFILES_PER_EMPLOYEE, build_profile_document
from app.profiles.schema import ProfileCreate, ProfileUpdate
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "profiles"

logger = logging.getLogger(__name__)


def _default_filters() -> dict:
    return {"country": [], "domain": [], "industry": [], "company": [], "type": []}


def _default_sending_options() -> dict:
    return {"dailyLimit": 100, "delayMin": 30, "delayMax": 90}


def _default_prompt_settings() -> dict:
    return {
        "personalizeGreeting": True,
        "improveGrammar": True,
        "improveProfessionalism": False,
        "aiRewrite": False,
        "customInstruction": "",
    }


async def _assert_owns_profile_or_admin(
    profile: dict, employee_id: str, is_admin: bool
) -> None:
    if not is_admin and profile["employeeId"] != employee_id:
        raise ForbiddenException("You do not have access to this profile")


async def create_profile(employee_id: str, payload: ProfileCreate) -> dict:
    profiles = get_collection(COLLECTION)

    count = await profiles.count_documents({"employeeId": employee_id})
    if count >= MAX_PROFILES_PER_EMPLOYEE:
        raise BadRequestException(
            f"Maximum of {MAX_PROFILES_PER_EMPLOYEE} profiles allowed per employee"
        )

    existing = await profiles.find_one(
        {"employeeId": employee_id, "profileName": payload.profileName}
    )
    if existing:
        raise ConflictException(
            "A profile with this name already exists for this employee"
        )

    doc = build_profile_document(
        employee_id=employee_id,
        profile_name=payload.profileName,
        gmail_account=str(payload.gmailAccount),
        signature=payload.signature,
        templates=[t.model_dump() for t in payload.templates],
        filters=payload.filters.model_dump(),
        filter_limit=payload.filterLimit,
        sending_options=payload.sendingOptions.model_dump(),
        prompt_settings=payload.promptSettings.model_dump(),
    )
    result = await profiles.insert_one(doc)
    created = await profiles.find_one({"_id": result.inserted_id})

    await create_notification(
        employee_id=employee_id,
        message=f"New profile '{payload.profileName}' was created successfully.",
        type=NotificationType.INFO,
    )

    return serialize_doc(created)


async def list_profiles(employee_id: str | None) -> list[dict]:
    profiles = get_collection(COLLECTION)
    query = {"employeeId": employee_id} if employee_id else {}
    cursor = profiles.find(query).sort("createdAt", -1)
    return serialize_list([d async for d in cursor])


async def get_profile(profile_id: str, employee_id: str, is_admin: bool) -> dict:
    profiles = get_collection(COLLECTION)
    doc = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not doc:
        raise NotFoundException("Profile not found")
    doc = serialize_doc(doc)
    await _assert_owns_profile_or_admin(doc, employee_id, is_admin)
    # Back-fill defaults for older documents that predate new fields
    doc.setdefault("signature", "")
    doc.setdefault("filters", _default_filters())
    doc.setdefault("filterLimit", 0)
    doc.setdefault("sendingOptions", _default_sending_options())
    doc.setdefault("promptSettings", _default_prompt_settings())
    return doc


async def update_profile(
    profile_id: str, employee_id: str, is_admin: bool, payload: ProfileUpdate
) -> dict:
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )

    update_data: dict = {}
    raw = payload.model_dump(exclude_unset=True)

    for key, val in raw.items():
        if val is not None:
            # Handle templates specially - convert to list of dicts
            if key == "templates" and val:
                update_data[key] = [t if isinstance(t, dict) else t.model_dump() for t in val]
            else:
                # nested pydantic objects come back as dicts via model_dump
                update_data[key] = val

    if not update_data:
        return serialize_doc(existing)

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {"$set": update_data},
        return_document=True,
    )
    return serialize_doc(result)


async def set_active_status(
    profile_id: str, employee_id: str, is_admin: bool, is_active: bool
) -> dict:
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )

    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {"$set": {"isActive": is_active, "updatedAt": datetime.now(timezone.utc)}},
        return_document=True,
    )
    return serialize_doc(result)


async def delete_profile(profile_id: str, employee_id: str, is_admin: bool) -> None:
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Delete the profile
    await profiles.delete_one({"_id": to_object_id(profile_id)})
    
    # Also delete all profile_emails records for this profile (cleanup orphaned records)
    profile_emails = get_collection("profile_emails")
    await profile_emails.delete_many({"profileId": profile_id})


async def add_template(
    profile_id: str, employee_id: str, is_admin: bool, template_data: dict
) -> dict:
    """Add a new template to a profile"""
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Generate unique template ID
    import uuid
    template_id = str(uuid.uuid4())[:8]
    
    new_template = {
        "id": template_id,
        "name": template_data.get("name", f"Template {template_id}"),
        "subject": template_data.get("subject", ""),
        "body": template_data.get("body", ""),
        "weight": template_data.get("weight", 1),
    }
    
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {
            "$push": {"templates": new_template},
            "$set": {"updatedAt": datetime.now(timezone.utc)}
        },
        return_document=True,
    )
    return serialize_doc(result)


async def update_template(
    profile_id: str, employee_id: str, is_admin: bool, template_id: str, template_data: dict
) -> dict:
    """Update an existing template in a profile"""
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Find template
    templates = existing.get("templates", [])
    template_idx = None
    for idx, t in enumerate(templates):
        if t.get("id") == template_id:
            template_idx = idx
            break
    
    if template_idx is None:
        raise NotFoundException(f"Template {template_id} not found")
    
    # Update template
    update_dict = {}
    if "name" in template_data:
        update_dict[f"templates.{template_idx}.name"] = template_data["name"]
    if "subject" in template_data:
        update_dict[f"templates.{template_idx}.subject"] = template_data["subject"]
    if "body" in template_data:
        update_dict[f"templates.{template_idx}.body"] = template_data["body"]
    if "weight" in template_data:
        update_dict[f"templates.{template_idx}.weight"] = template_data["weight"]
    
    update_dict["updatedAt"] = datetime.now(timezone.utc)
    
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {"$set": update_dict},
        return_document=True,
    )
    return serialize_doc(result)


async def delete_template(
    profile_id: str, employee_id: str, is_admin: bool, template_id: str
) -> dict:
    """Delete a template from a profile"""
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Must have at least one template
    templates = existing.get("templates", [])
    if len(templates) <= 1:
        raise BadRequestException("Cannot delete the last template")
    
    # Find and delete any attached files
    for template in templates:
        if template.get("id") == template_id:
            attachments = template.get("attachments", [])
            for attachment in attachments:
                filepath = attachment.get("filepath")
                if filepath:
                    _delete_file(filepath)
            break
    
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {
            "$pull": {"templates": {"id": template_id}},
            "$set": {"updatedAt": datetime.now(timezone.utc)}
        },
        return_document=True,
    )
    return serialize_doc(result)


async def upload_attachment(
    profile_id: str, template_id: str, file, employee_id: str, is_admin: bool
) -> dict:
    """Upload an attachment file for a template"""
    import os
    import uuid
    
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Find template
    templates = existing.get("templates", [])
    template_idx = None
    for idx, t in enumerate(templates):
        if t.get("id") == template_id:
            template_idx = idx
            break
    
    if template_idx is None:
        raise NotFoundException(f"Template {template_id} not found")
    
    # Validate file size (max 10MB)
    max_size = 10 * 1024 * 1024  # 10MB
    file_content = await file.read()
    if len(file_content) > max_size:
        raise BadRequestException(f"File too large. Maximum size is 10MB")
    
    # Validate file type (allow common attachment types)
    allowed_types = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/jpeg",
        "image/png",
        "image/gif",
        "text/plain",
        "text/csv",
    }
    
    if file.content_type not in allowed_types:
        raise BadRequestException(f"File type not allowed. Allowed: PDF, DOC, XLS, images, etc.")
    
    # Generate unique filename
    file_id = str(uuid.uuid4())[:8]
    file_ext = os.path.splitext(file.filename)[1]
    safe_filename = f"{file_id}_{file.filename}"
    filepath = f"uploads/templates/{safe_filename}"
    
    # Save file to disk
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "templates")
    os.makedirs(upload_dir, exist_ok=True)
    full_path = os.path.join(upload_dir, safe_filename)
    
    with open(full_path, "wb") as f:
        f.write(file_content)
    
    # Create attachment record
    attachment = {
        "id": file_id,
        "filename": file.filename,
        "filepath": filepath,
        "size": len(file_content),
    }
    
    # Add attachment to template
    update_dict = {f"templates.{template_idx}.attachments": attachment}
    update_dict["updatedAt"] = datetime.now(timezone.utc)
    
    # Use $push to add to attachments array
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {"$push": {f"templates.{template_idx}.attachments": attachment}, "$set": {"updatedAt": datetime.now(timezone.utc)}},
        return_document=True,
    )
    return serialize_doc(result)


async def delete_attachment(
    profile_id: str, template_id: str, attachment_id: str, employee_id: str, is_admin: bool
) -> dict:
    """Delete an attachment from a template"""
    import os
    
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Find template and attachment
    templates = existing.get("templates", [])
    template_idx = None
    attachment_path = None
    
    for idx, template in enumerate(templates):
        if template.get("id") == template_id:
            template_idx = idx
            for att in template.get("attachments", []):
                if att.get("id") == attachment_id:
                    attachment_path = att.get("filepath")
                    break
            break
    
    if template_idx is None:
        raise NotFoundException(f"Template {template_id} not found")
    
    if not attachment_path:
        raise NotFoundException(f"Attachment {attachment_id} not found")
    
    # Delete file from disk
    _delete_file(attachment_path)
    
    # Remove from database
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {
            "$pull": {f"templates.{template_idx}.attachments": {"id": attachment_id}},
            "$set": {"updatedAt": datetime.now(timezone.utc)}
        },
        return_document=True,
    )
    return serialize_doc(result)


def _delete_file(filepath: str) -> None:
    """Helper to safely delete a file"""
    import os
    try:
        full_path = os.path.join(os.path.dirname(__file__), "..", "..", filepath)
        if os.path.exists(full_path):
            os.remove(full_path)
    except Exception as e:
        logger.warning(f"Failed to delete file {filepath}: {e}")
