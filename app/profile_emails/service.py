from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.database.mongodb import get_collection
from app.email_master.service import mark_assigned_to_profile, query_for_profile
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.profile_emails.model import SendStatus, build_profile_email_document
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
    limit_override: int | None = None,
) -> dict:
    """
    Read email_master applying profile filters, snapshot matching records
    into profile_emails.  Existing PENDING records for this profile are
    replaced; SENT / SENDING rows are preserved to avoid losing tracking.
    """
    profile = await get_profile(profile_id, employee_id, is_admin)

    filters: dict = override_filters or profile.get("filters", {})
    sending_opts: dict = profile.get("sendingOptions", {})
    daily_limit: int = limit_override or sending_opts.get("dailyLimit", 100)
    filter_limit: int = profile.get("filterLimit", 0)

    # Pull matching unique records from email_master
    master_records = await query_for_profile(
        employee_id=profile["employeeId"],
        filters=filters,
        daily_limit=daily_limit,
        filter_limit=filter_limit,
    )

    if not master_records:
        raise BadRequestException(
            "No matching records found in Email Master for the current profile filters. "
            "Adjust the filters or upload more leads."
        )

    profile_emails_col = get_collection(COLLECTION)

    # Remove only PENDING rows — preserve already-sent/failed/sending rows
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

    # Update email_master assigned_profiles
    if master_ids_to_mark:
        await mark_assigned_to_profile(
            master_ids=master_ids_to_mark,
            profile_id=profile_id,
            employee_id=profile["employeeId"],
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
    send_status: str | None = None,
    search: str | None = None,
    country: str | None = None,
    domain: str | None = None,
) -> dict:
    # Ownership check
    await get_profile(profile_id, employee_id, is_admin)

    col = get_collection(COLLECTION)
    query: dict = {"profileId": profile_id}

    if send_status:
        query["sendStatus"] = send_status
    if country:
        query["country"] = country
    if domain:
        query["domain"] = domain
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"fullName": {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
        ]

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
        {"$group": {"_id": "$sendStatus", "count": {"$sum": 1}}},
    ]
    rows = col.aggregate(pipeline)
    counts: dict[str, int] = {}
    async for row in rows:
        counts[row["_id"]] = row["count"]

    total = sum(counts.values())
    return {
        "total": total,
        "pending": counts.get(SendStatus.PENDING.value, 0),
        "sending": counts.get(SendStatus.SENDING.value, 0),
        "sent": counts.get(SendStatus.SENT.value, 0),
        "failed": counts.get(SendStatus.FAILED.value, 0),
        "skipped": counts.get(SendStatus.SKIPPED.value, 0),
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
    result = await col.delete_many({"profileId": profile_id})
    return {"deletedCount": result.deleted_count}


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
    if not is_admin:
        # Only delete rows that belong to this employee
        result = await col.delete_many(
            {"_id": {"$in": object_ids}, "employeeId": employee_id}
        )
    else:
        result = await col.delete_many({"_id": {"$in": object_ids}})

    return {"deletedCount": result.deleted_count}


# ---------------------------------------------------------------------------
# Internal helpers used by the campaign engine
# ---------------------------------------------------------------------------

async def get_pending_batch(
    profile_id: str, batch_size: int
) -> list[dict]:
    """Fetch the next batch of PENDING rows for a campaign run."""
    col = get_collection(COLLECTION)
    cursor = (
        col.find({"profileId": profile_id, "sendStatus": SendStatus.PENDING.value})
        .sort("createdAt", 1)
        .limit(batch_size)
    )
    return serialize_list([d async for d in cursor])


async def mark_sending(profile_email_id: str) -> None:
    col = get_collection(COLLECTION)
    await col.update_one(
        {"_id": to_object_id(profile_email_id)},
        {"$set": {"sendStatus": SendStatus.SENDING.value, "updatedAt": datetime.now(timezone.utc)}},
    )


async def mark_sent(
    profile_email_id: str,
    thread_id: str | None,
    message_id: str | None,
) -> None:
    col = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    await col.update_one(
        {"_id": to_object_id(profile_email_id)},
        {
            "$set": {
                "sendStatus": SendStatus.SENT.value,
                "threadId": thread_id,
                "messageId": message_id,
                "sentDate": now,
                "errorMessage": None,
                "updatedAt": now,
            }
        },
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
