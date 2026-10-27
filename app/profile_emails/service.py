from datetime import datetime, timezone
import re
from typing import Any

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.database.mongodb import get_collection
from app.email_master.service import (
    decrement_email_usage,
    mark_used_in_profile,
    mark_emails_assigned_to_employee,
    query_for_profile,
    release_email_locks,
)
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.profile_emails.model import ProfileEmailType, SendStatus, build_profile_email_document
from app.profiles.service import get_profile
from app.schemas.common import PaginationParams
from app.utils.pagination import build_paginated_response
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "profile_emails"


# ---------------------------------------------------------------------------
# Generate list
# ---------------------------------------------------------------------------

async def generate_list(
    profile_id: str,
    employee_id: str,
    is_admin: bool,
    override_filters: dict | None = None,
    allow_used: bool = False,
) -> dict:
    """
    Read email_master applying profile filters, snapshot matching records
    into profile_emails.  Existing PENDING records for this profile are
    replaced; SENT / SENDING rows are preserved to avoid losing tracking.
    """
    profile = await get_profile(profile_id, employee_id, is_admin)

    filters: dict = override_filters or profile.get("filters", {})
    # Inject the allow_used flag: request value takes priority, else fall back to profile's stored setting
    filters["allowUsed"] = allow_used or filters.get("allowUsed", False)
    generation_limit = int(profile.get("filterLimit") or 0)
    profile_emails_col = get_collection(COLLECTION)
    
    # CHECK: Profile email generation LOCK
    # If profile already has emails generated, cannot generate again
    # unless they delete them first or send and clear
    existing_emails_count = await profile_emails_col.count_documents(
        {"profileId": profile_id, "sendStatus": SendStatus.PENDING.value}
    )
    
    if existing_emails_count > 0:
        raise BadRequestException(
            f"❌ Cannot generate more emails. This profile already has {existing_emails_count} pending emails. "
            f"To generate again, you must:\n"
            f"(1) Send all pending emails via a campaign, then delete the sent emails\n"
            f"(2) OR manually delete all pending emails from this profile\n"
            f"Then you can generate a new batch."
        )

    # Pull matching unique records from GLOBAL email_master
    # Pass employee_id so query skips emails assigned to OTHER employees
    master_records = await query_for_profile(
        filters=filters,
        daily_limit=0,
        filter_limit=generation_limit,
        employee_id=profile["employeeId"],  # Pass employee ID
    )

    if not master_records:
        # Count total emails in master to help diagnose
        master_col = get_collection(COLLECTION)
        total_in_master = await master_col.count_documents({"isDuplicate": False})
        
        if total_in_master == 0:
            raise BadRequestException(
                "❌ Email Master is empty. Please upload emails first via the 'Email Master' page. "
                "After uploading, all employees can use them in their profiles."
            )
        else:
            raise BadRequestException(
                f"❌ No emails match your profile filters. "
                f"Email Master has {total_in_master} emails, but none match your current filters. "
                f"Try: (1) Removing filters to use all emails, (2) Uploading more emails, "
                f"or (3) Checking filter values match your data."
            )

    # Remove only PENDING rows — preserve already-sent/failed/sending rows
    pending_cursor = profile_emails_col.find(
        {"profileId": profile_id, "sendStatus": SendStatus.PENDING.value},
        {"masterEmailId": 1}
    )
    pending_master_ids = [doc["masterEmailId"] async for doc in pending_cursor]
    
    if pending_master_ids:
        await release_email_locks(pending_master_ids)

    await profile_emails_col.delete_many(
        {"profileId": profile_id, "sendStatus": SendStatus.PENDING.value}
    )

    # Determine which master_ids are already tracked (sent/failed) to skip re-adding
    already_tracked_cursor = profile_emails_col.find(
        {"profileId": profile_id, "sendStatus": {"$ne": SendStatus.PENDING.value}},
        {"masterEmailId": 1},
    )
    already_tracked_ids: set[str] = {
        doc["masterEmailId"] async for doc in already_tracked_cursor
    }

    new_docs: list[dict] = []
    master_ids_to_mark: list[str] = []

    for record in master_records:
        master_id = record["id"]
        if master_id in already_tracked_ids:
            continue
        new_docs.append(
            build_profile_email_document(
                profile_id=profile_id,
                employee_id=profile["employeeId"],
                master_email_id=master_id,
                record=record,
            )
        )
        master_ids_to_mark.append(master_id)

    if new_docs:
        await profile_emails_col.insert_many(new_docs)

    # Update email_master usedInProfiles tracking
    if master_ids_to_mark:
        await mark_used_in_profile(
            master_ids=master_ids_to_mark,
            profile_id=profile_id,
            employee_id=profile["employeeId"],
            profile_name=profile["profileName"],
        )
        
        # Also mark emails as assigned to this employee (claim them)
        # Get employee name from employees collection
        from app.employees.service import get_employee
        try:
            employee = await get_employee(profile["employeeId"])
            employee_name = employee.get("name", profile["employeeId"])
        except:
            employee_name = profile["employeeId"]
        
        await mark_emails_assigned_to_employee(
            master_ids=master_ids_to_mark,
            employee_id=profile["employeeId"],
            employee_name=employee_name,
        )

    total_pending = await profile_emails_col.count_documents(
        {"profileId": profile_id, "sendStatus": SendStatus.PENDING.value}
    )

    await create_notification(
        employee_id=profile["employeeId"],
        message=(
            f"Profile '{profile['profileName']}': list generated with "
            f"{total_pending} pending email(s)."
        ),
        type=NotificationType.INFO,
    )

    return {
        "profileId": profile_id,
        "added": len(new_docs),
        "skipped": len(master_records) - len(new_docs),
        "totalPending": total_pending,
    }


# ---------------------------------------------------------------------------
# List / query
# ---------------------------------------------------------------------------

async def list_profile_emails(
    profile_id: str,
    employee_id: str,
    is_admin: bool,
    params: PaginationParams,
    mail_type: str | None = None,
    send_status: str | None = None,
    search: str | None = None,
    country: str | None = None,
    domain: str | None = None,
) -> dict:
    # Ownership check
    await get_profile(profile_id, employee_id, is_admin)

    col = get_collection(COLLECTION)
    query: dict = {"profileId": profile_id}
    or_filters: list[dict] = []

    if mail_type == ProfileEmailType.DRAFT.value:
        or_filters.append(
            {
                "$or": [
                    {"mailType": ProfileEmailType.DRAFT.value},
                    {"mailType": {"$exists": False}},
                ]
            }
        )
    elif mail_type:
        query["mailType"] = mail_type
    if send_status:
        query["sendStatus"] = send_status
    if country:
        query["country"] = country
    if domain:
        query["domain"] = domain
    if search:
        or_filters.append(
            {
                "$or": [
                    {"email": {"$regex": search, "$options": "i"}},
                    {"fullName": {"$regex": search, "$options": "i"}},
                    {"university": {"$regex": search, "$options": "i"}},
                ]
            }
        )
    if or_filters:
        query["$and"] = or_filters

    total = await col.count_documents(query)
    cursor = (
        col.find(query)
        .sort("createdAt", 1)
        .skip(params.skip)
        .limit(params.pageSize)
    )
    docs = serialize_list([d async for d in cursor])
    return build_paginated_response(docs, total, params)


async def get_stats(profile_id: str, employee_id: str, is_admin: bool) -> dict:
    await get_profile(profile_id, employee_id, is_admin)
    col = get_collection(COLLECTION)

    pipeline = [
        {"$match": {"profileId": profile_id}},
        {
            "$group": {
                "_id": {
                    "mailType": {"$ifNull": ["$mailType", ProfileEmailType.DRAFT.value]},
                    "sendStatus": "$sendStatus",
                },
                "count": {"$sum": 1},
            }
        },
    ]
    rows = col.aggregate(pipeline)
    counts: dict[str, int] = {}
    by_type = {
        mail_type.value: {
            "total": 0,
            "pending": 0,
            "sending": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
        }
        for mail_type in ProfileEmailType
    }
    async for row in rows:
        mail_type = row["_id"]["mailType"]
        send_status = row["_id"]["sendStatus"]
        count = row["count"]
        counts[send_status] = counts.get(send_status, 0) + count
        if mail_type in by_type:
            by_type[mail_type]["total"] += count
            if send_status in by_type[mail_type]:
                by_type[mail_type][send_status] += count

    total = sum(counts.values())
    return {
        "total": total,
        "pending": counts.get(SendStatus.PENDING.value, 0),
        "sending": counts.get(SendStatus.SENDING.value, 0),
        "sent": counts.get(SendStatus.SENT.value, 0),
        "failed": counts.get(SendStatus.FAILED.value, 0),
        "skipped": counts.get(SendStatus.SKIPPED.value, 0),
        "byType": by_type,
    }


async def convert_sent_drafts_to_reminders(
    profile_id: str,
    employee_id: str,
    is_admin: bool,
) -> dict:
    """Queue sent drafts with saved subject and Message-ID for reminder campaigns."""
    await get_profile(profile_id, employee_id, is_admin)
    col = get_collection(COLLECTION)
    cursor = col.find(
        {
            "profileId": profile_id,
            "sendStatus": SendStatus.SENT.value,
            "$or": [
                {"mailType": ProfileEmailType.DRAFT.value},
                {"mailType": {"$exists": False}},
            ],
        }
    )
    converted_count = 0
    skipped_missing_thread_data = 0
    now = datetime.now(timezone.utc)

    async for doc in cursor:
        original_subject = doc.get("draftSubject")
        original_message_id = doc.get("draftMessageId") or doc.get("messageId")
        if not original_subject or not original_message_id:
            skipped_missing_thread_data += 1
            continue

        result = await col.update_one(
            {
                "_id": doc["_id"],
                "sendStatus": SendStatus.SENT.value,
                "$or": [
                    {"mailType": ProfileEmailType.DRAFT.value},
                    {"mailType": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "mailType": ProfileEmailType.REMINDER.value,
                    "sendStatus": SendStatus.PENDING.value,
                    "draftSubject": original_subject,
                    "draftMessageId": original_message_id,
                    "updatedAt": now,
                }
            },
        )
        converted_count += result.modified_count

    return {
        "profileId": profile_id,
        "convertedCount": converted_count,
        "skippedMissingThreadData": skipped_missing_thread_data,
    }


# ---------------------------------------------------------------------------
# CRUD on individual rows
# ---------------------------------------------------------------------------

async def get_profile_email(
    profile_email_id: str,
    employee_id: str,
    is_admin: bool,
) -> dict:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(profile_email_id)})
    if not doc:
        raise NotFoundException("Profile email record not found")
    if not is_admin and doc.get("employeeId") != employee_id:
        raise ForbiddenException("Access denied")
    return serialize_doc(doc)


async def update_profile_email(
    profile_email_id: str,
    employee_id: str,
    is_admin: bool,
    payload: dict[str, Any],
) -> dict:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(profile_email_id)})
    if not doc:
        raise NotFoundException("Profile email record not found")
    if not is_admin and doc.get("employeeId") != employee_id:
        raise ForbiddenException("Access denied")

    update_data = {k: v for k, v in payload.items() if v is not None}
    if not update_data:
        return serialize_doc(doc)

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await col.find_one_and_update(
        {"_id": to_object_id(profile_email_id)},
        {"$set": update_data},
        return_document=True,
    )
    return serialize_doc(result)


async def delete_profile_email(
    profile_email_id: str,
    employee_id: str,
    is_admin: bool,
) -> None:
    """
    Delete a single row from profile_emails only.
    Email Master is never touched.
    """
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(profile_email_id)})
    if not doc:
        raise NotFoundException("Profile email record not found")
    if not is_admin and doc.get("employeeId") != employee_id:
        raise ForbiddenException("Access denied")
    master_email_id = doc.get("masterEmailId")
    if master_email_id:
        await release_email_locks([master_email_id])
        
    await col.delete_one({"_id": to_object_id(profile_email_id)})


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

async def retry_failed(profile_id: str, employee_id: str, is_admin: bool) -> dict:
    """Reset all FAILED rows in this profile back to PENDING for the next campaign run."""
    await get_profile(profile_id, employee_id, is_admin)
    col = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    result = await col.update_many(
        {"profileId": profile_id, "sendStatus": SendStatus.FAILED.value},
        {
            "$set": {
                "sendStatus": SendStatus.PENDING.value,
                "errorMessage": None,
                "updatedAt": now,
            },
            "$inc": {"retryCount": 1},
        },
    )
    return {"resetCount": result.modified_count}


async def clear_profile_list(profile_id: str, employee_id: str, is_admin: bool) -> dict:
    """
    Delete ALL profile_email rows for this profile.
    Email Master is never touched.  Use before re-generating with new filters.
    """
    await get_profile(profile_id, employee_id, is_admin)
    col = get_collection(COLLECTION)
    
    cursor = col.find(
        {"profileId": profile_id},
        {"masterEmailId": 1, "sendStatus": 1, "mailType": 1},
    )
    master_ids: list[str] = []
    unused_master_ids: list[str] = []
    async for doc in cursor:
        master_id = doc.get("masterEmailId")
        if not master_id:
            continue
        master_ids.append(master_id)
        # Reminder rows are pending after their original draft was sent, so
        # they must retain their usage count. Missing mailType means legacy draft.
        if (
            doc.get("sendStatus") == SendStatus.PENDING.value
            and doc.get("mailType", ProfileEmailType.DRAFT.value)
            == ProfileEmailType.DRAFT.value
        ):
            unused_master_ids.append(master_id)

    if master_ids:
        await release_email_locks(master_ids)
        
    result = await col.delete_many({"profileId": profile_id})
    usage_reversed = await decrement_email_usage(unused_master_ids)
    return {
        "deletedCount": result.deleted_count,
        "usageCountReversed": usage_reversed,
    }


async def bulk_delete(
    profile_email_ids: list[str],
    employee_id: str,
    is_admin: bool,
) -> dict:
    col = get_collection(COLLECTION)
    from bson import ObjectId

    object_ids = [
        ObjectId(i) for i in profile_email_ids if ObjectId.is_valid(i)
    ]
    
    query = {"_id": {"$in": object_ids}}
    if not is_admin:
        query["employeeId"] = employee_id
        
    # Get all masterEmailIds before deleting
    cursor = col.find(query, {"masterEmailId": 1})
    master_ids = [doc["masterEmailId"] async for doc in cursor if doc.get("masterEmailId")]
    if master_ids:
        await release_email_locks(master_ids)

    result = await col.delete_many(query)

    return {"deletedCount": result.deleted_count}


# ---------------------------------------------------------------------------
# Internal helpers used by the campaign engine
# ---------------------------------------------------------------------------

async def get_pending_batch(
    profile_id: str,
    batch_size: int,
    excluded_domains: set[str] | None = None,
    mail_type: str = ProfileEmailType.DRAFT.value,
) -> list[dict]:
    """Fetch the next batch of PENDING rows for a campaign run."""
    col = get_collection(COLLECTION)
    query: dict = {
        "profileId": profile_id,
        "sendStatus": SendStatus.PENDING.value,
    }
    if mail_type == ProfileEmailType.DRAFT.value:
        query["$or"] = [
            {"mailType": ProfileEmailType.DRAFT.value},
            {"mailType": {"$exists": False}},
        ]
    else:
        query["mailType"] = mail_type
    if excluded_domains:
        query["$and"] = [
            {
                "email": {
                    "$not": {
                        "$regex": f"@{re.escape(domain)}$",
                        "$options": "i",
                    }
                }
            }
            for domain in excluded_domains
        ]
    sort_fields = (
        [("sentDate", 1), ("createdAt", 1)]
        if mail_type == ProfileEmailType.REMINDER.value
        else [("createdAt", 1)]
    )
    cursor = col.find(query).sort(sort_fields).limit(batch_size)
    return serialize_list([d async for d in cursor])


async def get_sent_domain_counts_today(profile_id: str) -> dict[str, int]:
    """Count this profile's successfully sent recipients per domain today (UTC)."""
    col = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cursor = col.find(
        {
            "profileId": profile_id,
            "sendStatus": SendStatus.SENT.value,
            "sentDate": {"$gte": day_start},
        },
        {"email": 1},
    )

    counts: dict[str, int] = {}
    async for doc in cursor:
        domain = str(doc.get("email") or "").rsplit("@", 1)
        if len(domain) == 2 and domain[1]:
            key = domain[1].casefold()
            counts[key] = counts.get(key, 0) + 1
    return counts


async def mark_sending(profile_email_id: str) -> bool:
    col = get_collection(COLLECTION)
    result = await col.update_one(
        {
            "_id": to_object_id(profile_email_id),
            "sendStatus": SendStatus.PENDING.value,
        },
        {"$set": {"sendStatus": SendStatus.SENDING.value, "updatedAt": datetime.now(timezone.utc)}},
    )
    return result.modified_count == 1


async def mark_sent(
    profile_email_id: str,
    thread_id: str | None,
    message_id: str | None,
    template_id: str | None = None,
    mail_type: str = ProfileEmailType.DRAFT.value,
    subject: str | None = None,
) -> None:
    col = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    update_fields = {
        "sendStatus": SendStatus.SENT.value,
        "threadId": thread_id,
        "messageId": message_id,
        "sentDate": now,
        "errorMessage": None,
        "templateId": template_id or "default",
        "updatedAt": now,
    }
    if mail_type == ProfileEmailType.DRAFT.value:
        update_fields.update(
            {
                "draftSubject": subject,
                "draftMessageId": message_id,
                "draftSentDate": now,
            }
        )
    else:
        update_fields.update(
            {
                "reminderSubject": subject,
                "reminderMessageId": message_id,
                "reminderSentDate": now,
            }
        )
    await col.update_one(
        {"_id": to_object_id(profile_email_id)},
        {"$set": update_fields},
    )


async def mark_failed(profile_email_id: str, error: str) -> None:
    col = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    await col.update_one(
        {"_id": to_object_id(profile_email_id)},
        {
            "$set": {
                "sendStatus": SendStatus.FAILED.value,
                "errorMessage": error[:500],
                "updatedAt": now,
            }
        },
    )


async def mark_pending(profile_email_id: str) -> None:
    """Revert a SENDING/FAILED row back to PENDING (e.g. on SMTP limits)."""
    col = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    await col.update_one(
        {"_id": to_object_id(profile_email_id)},
        {
            "$set": {
                "sendStatus": SendStatus.PENDING.value,
                "errorMessage": None,
                "updatedAt": now,
            }
        },
    )
