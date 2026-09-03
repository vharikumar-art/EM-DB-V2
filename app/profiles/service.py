from datetime import datetime, timezone
import logging
import random

from fastapi import UploadFile
from app.campaign_engine.sender import SMTPCredentials, send_email
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.database.mongodb import get_collection
from app.email_accounts.service import get_credentials_for_send
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.profiles.model import MAX_PROFILES_PER_EMPLOYEE, build_profile_document
from app.profiles.schema import ProfileCreate, ProfileTestEmailRequest, ProfileUpdate

MAX_PROFILE_EMAIL_GENERATION_LIMIT = 600
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "profiles"

logger = logging.getLogger(__name__)


def _default_filters() -> dict:
    return {"country": [], "domain": [], "domainGroup": [], "university": [], "type": []}


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
    profile: dict, employee_id: str | list[str] | None, is_admin: bool
) -> None:
    if not is_admin:
        profile_owner = profile.get("employeeId")
        if isinstance(employee_id, list):
            if profile_owner not in employee_id:
                raise ForbiddenException("You do not have access to this profile")
        elif profile_owner != employee_id:
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
        attachments=[a.model_dump() for a in payload.attachments] if payload.attachments else [],
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


async def list_profiles(employee_id: str | list[str] | None) -> list[dict]:
    profiles = get_collection(COLLECTION)
    if employee_id is None:
        query = {}
    elif isinstance(employee_id, list):
        query = {"employeeId": {"$in": employee_id}}
    else:
        query = {"employeeId": employee_id}
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

    if "filterLimit" in raw and raw["filterLimit"] is not None and raw["filterLimit"] > MAX_PROFILE_EMAIL_GENERATION_LIMIT:
        raise BadRequestException(
            f"Filter limit cannot exceed {MAX_PROFILE_EMAIL_GENERATION_LIMIT}"
        )

    if "sendingOptions" in raw and raw["sendingOptions"] is not None:
        sending_options = raw["sendingOptions"]
        if isinstance(sending_options, dict) and sending_options.get("dailyLimit") is not None:
            daily_limit = sending_options["dailyLimit"]
            if daily_limit > MAX_PROFILE_EMAIL_GENERATION_LIMIT:
                raise BadRequestException(
                    f"Daily limit cannot exceed {MAX_PROFILE_EMAIL_GENERATION_LIMIT}"
                )

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

    # Cascade the employeeId change to campaigns, profile_emails, and the linked email account
    if "employeeId" in update_data and update_data["employeeId"] != existing.get("employeeId"):
        new_emp_id = update_data["employeeId"]
        now = datetime.now(timezone.utc)
        await get_collection("campaigns").update_many(
            {"profileId": profile_id},
            {"$set": {"employeeId": new_emp_id, "updatedAt": now}}
        )
        await get_collection("profile_emails").update_many(
            {"profileId": profile_id},
            {"$set": {"employeeId": new_emp_id, "updatedAt": now}}
        )
        # Also move the associated email account to the new employee
        if existing.get("gmailAccount"):
            await get_collection("email_accounts").update_many(
                {"email": existing["gmailAccount"]},
                {"$set": {"employeeId": new_emp_id, "updatedAt": now}}
            )

    return serialize_doc(result)


async def send_test_email(
    profile_id: str,
    employee_id: str,
    is_admin: bool,
    payload: ProfileTestEmailRequest,
) -> dict:
    """Send a real test email for a profile using that profile's configured sender and template."""
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(serialize_doc(existing), employee_id, is_admin)

    templates = existing.get("templates") or []
    if not templates:
        raise BadRequestException("This profile has no templates configured")

    template = None
    if payload.templateId:
        for item in templates:
            if str(item.get("id")) == str(payload.templateId):
                template = item
                break
    if template is None:
        template = random.choice(templates)

    sender_email = str(existing.get("gmailAccount") or "").strip()
    if not sender_email:
        raise BadRequestException("This profile does not have a sender email configured")

    credentials = await get_credentials_for_send(sender_email)
    subject = _replace_placeholders(str(template.get("subject") or ""), {"name": "Test", "fullName": "Test"})
    body = _replace_placeholders(str(template.get("body") or ""), {"name": "Test", "fullName": "Test"})
    signature = str(existing.get("signature") or "")
    html_body = f"{body.replace(chr(10), '<br>')}<br><br>{signature}"

    attachments = []
    for item in (existing.get("attachments") or []):
        attachments.append({
            "filename": item.get("filename", "attachment"),
            "filepath": item.get("filepath"),
        })
    for item in (template.get("attachments") or []):
        attachments.append({
            "filename": item.get("filename", "attachment"),
            "filepath": item.get("filepath"),
        })

    seen = set()
    unique_attachments = []
    for item in attachments:
        key = (item.get("filepath"), item.get("filename"))
        if key in seen or not item.get("filepath"):
            continue
        seen.add(key)
        unique_attachments.append(item)

    smtp_credentials = SMTPCredentials(
        email=credentials["email"],
        password=credentials["password"],
        display_name=credentials.get("displayName", credentials["email"]),
        smtp_host=credentials["smtpHost"],
        smtp_port=credentials["smtpPort"],
        use_tls=bool(credentials.get("useTls", True)),
    )

    result = await send_email(
        credentials=smtp_credentials,
        to=str(payload.toEmail),
        subject=subject,
        body_plain=body,
        body_html=html_body,
        attachments=unique_attachments,
    )

    return {
        "success": bool(result.success),
        "message": "Test email sent successfully" if result.success else (result.error or "Test email failed"),
        "fromEmail": credentials["email"],
        "toEmail": str(payload.toEmail),
        "subject": subject,
        "messageId": result.message_id,
        "attachments": unique_attachments,
        "error": result.error,
    }


def _replace_placeholders(text: str, lead: dict) -> str:
    """Simple [placeholder] substitution for preview and test sends."""
    replacements = {
        "[name]": lead.get("fullName") or lead.get("name") or "there",
        "[university]": lead.get("university", "your university"),
        "[industry]": lead.get("industry", "your industry"),
        "[designation]": lead.get("designation", ""),
        "[country]": lead.get("country", ""),
        "[domain]": lead.get("domain", ""),
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value.strip() if isinstance(value, str) else value)
    return text


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


async def upload_profile_attachment(
    profile_id: str, file: UploadFile, employee_id: str, is_admin: bool
) -> dict:
    """Upload an attachment file for the profile (shared across all templates)"""
    import os
    import uuid
    
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Validate file size (max 10MB)
    max_size = 10 * 1024 * 1024  # 10MB
    file_content = await file.read()
    if len(file_content) > max_size:
        raise BadRequestException("File too large. Maximum size is 10MB")
    
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
        raise BadRequestException("File type not allowed. Allowed: PDF, DOC, XLS, images, etc.")
    
    # Generate unique filename
    file_id = str(uuid.uuid4())[:8]
    file_ext = os.path.splitext(file.filename)[1]
    safe_filename = f"{file_id}_{file.filename}"
    
    # Save to local filesystem
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "profiles")
    os.makedirs(upload_dir, exist_ok=True)
    
    filepath = os.path.join(upload_dir, safe_filename)
    with open(filepath, "wb") as f:
        f.write(file_content)
    
    # Only one attachment per profile - replace if exists
    relative_filepath = f"uploads/profiles/{safe_filename}"
    attachment = {
        "id": file_id,
        "filename": file.filename,
        "filepath": relative_filepath,
        "size": len(file_content),
    }
    
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {
            "$set": {
                "attachments": [attachment],  # Replace all attachments with this one
                "updatedAt": datetime.now(timezone.utc)
            }
        },
        return_document=True,
    )
    
    return serialize_doc(result)


async def delete_profile_attachment(
    profile_id: str, attachment_id: str, employee_id: str, is_admin: bool
) -> dict:
    """Delete an attachment from a profile"""
    profiles = get_collection(COLLECTION)
    existing = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not existing:
        raise NotFoundException("Profile not found")
    await _assert_owns_profile_or_admin(
        serialize_doc(existing), employee_id, is_admin
    )
    
    # Find attachment to delete
    attachments = existing.get("attachments", [])
    attachment_idx = None
    filepath_to_delete = None
    
    for idx, att in enumerate(attachments):
        if att.get("id") == attachment_id:
            attachment_idx = idx
            filepath_to_delete = att.get("filepath")
            break
    
    if attachment_idx is None:
        raise NotFoundException(f"Attachment {attachment_id} not found")
    
    # Delete from filesystem
    if filepath_to_delete:
        _delete_file(filepath_to_delete)
    
    # Remove from profile
    result = await profiles.find_one_and_update(
        {"_id": to_object_id(profile_id)},
        {
            "$pull": {"attachments": {"id": attachment_id}},
            "$set": {"updatedAt": datetime.now(timezone.utc)}
        },
        return_document=True,
    )
    
    return serialize_doc(result)
