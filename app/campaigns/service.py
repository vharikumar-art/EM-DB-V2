from datetime import datetime, timezone, timedelta

from app.campaigns.model import CampaignStatus, build_campaign_document
from app.campaigns.schema import CampaignStartRequest
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.database.mongodb import get_collection
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.profile_emails.model import SendStatus
from app.profiles.service import get_profile
from app.schemas.common import PaginationParams
from app.utils.pagination import build_paginated_response
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "campaigns"
ACTIVE_CAMPAIGN_STATUSES = [
    CampaignStatus.PENDING.value,
    CampaignStatus.RUNNING.value,
    CampaignStatus.PAUSED.value,
    CampaignStatus.SCHEDULED.value,
    CampaignStatus.PROCESSING.value,
]


def _profile_email_type_filter(mail_type: str) -> dict:
    if mail_type == "draft":
        return {
            "$or": [
                {"mailType": "draft"},
                {"mailType": {"$exists": False}},
            ]
        }
    return {"mailType": mail_type}


def _add_campaign_progress(doc: dict) -> dict:
    result = serialize_doc(doc)
    total = max(int(result.get("totalEmails") or 0), 0)
    processed = sum(
        max(int(result.get(field) or 0), 0)
        for field in ("sent", "failed", "skipped")
    )
    result["processedEmails"] = processed
    result["progressPercent"] = round((processed / total) * 100, 1) if total else 0
    return result


async def claim_campaign_worker(campaign_id: str, worker_token: str) -> bool:
    """Atomically allow only one worker to execute a campaign at a time."""
    campaigns = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=30)
    result = await campaigns.find_one_and_update(
        {
            "_id": to_object_id(campaign_id),
            "$or": [
                {"workerLock": {"$exists": False}},
                {"workerLock": None},
                {"workerLockAt": {"$lt": stale_before}},
            ],
        },
        {
            "$set": {
                "workerLock": worker_token,
                "workerLockAt": now,
                "updatedAt": now,
            }
        },
    )
    return result is not None


async def release_campaign_worker(campaign_id: str, worker_token: str) -> None:
    """Release a campaign worker lock only when owned by this worker."""
    campaigns = get_collection(COLLECTION)
    await campaigns.update_one(
        {
            "_id": to_object_id(campaign_id),
            "workerLock": worker_token,
        },
        {
            "$set": {
                "workerLock": None,
                "workerLockAt": None,
                "updatedAt": datetime.now(timezone.utc),
            }
        },
    )


# ---------------------------------------------------------------------------
# Create / start
# ---------------------------------------------------------------------------

async def create_campaign(
    payload: CampaignStartRequest,
    employee_id: str,
    is_admin: bool,
) -> dict:
    """
    Validate, count pending emails, create the campaign document.
    The actual async send loop is started by the router via BackgroundTasks.
    
    Uses dailyLimit from request (not from profile).
    """
    profile = await get_profile(payload.profileId, employee_id, is_admin)

    if not profile.get("isActive", False):
        raise BadRequestException(
            "Profile is not active. Activate it before starting a campaign."
        )

    # Count pending rows of the selected mail type.
    profile_emails_col = get_collection("profile_emails")
    pending_query = {
        "profileId": payload.profileId,
        "sendStatus": SendStatus.PENDING.value,
        **_profile_email_type_filter(payload.mailType),
    }
    pending_count = await profile_emails_col.count_documents(pending_query)

    if pending_count == 0:
        raise BadRequestException(
            f"No pending {payload.mailType} emails in this profile's list. "
            + (
                "Generate the list first or retry failed emails."
                if payload.mailType == "draft"
                else "Convert sent drafts to reminders first."
            )
        )

    # Draft and reminder campaigns may run in parallel, but not two of the same type.
    campaigns = get_collection(COLLECTION)
    active_campaign = await campaigns.find_one(
        {
            "profileId": payload.profileId,
            **_profile_email_type_filter(payload.mailType),
            "status": {"$in": ACTIVE_CAMPAIGN_STATUSES},
        }
    )
    if active_campaign:
        raise BadRequestException(
            f"Cannot create {payload.mailType} campaign. This profile already has an active "
            f"{payload.mailType} campaign: '{active_campaign.get('campaignName')}'\n"
            f"Status: {active_campaign.get('status')}\n"
            "Wait for it to complete, or pause/delete it first."
        )

    # Use dailyLimit from request, default to profile's dailyLimit if not provided
    daily_limit = payload.dailyLimit or profile.get("sendingOptions", {}).get("dailyLimit", 100)

    campaign_name = (
        payload.campaignName.strip()
        or f"{profile['profileName']} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )

    doc = build_campaign_document(
        profile_id=payload.profileId,
        employee_id=profile["employeeId"],
        campaign_name=campaign_name,
        total_emails=pending_count,
        mail_type=payload.mailType,
    )
    # Snapshot relevant profile fields for audit trail
    doc["profileSnapshot"] = {
        "profileName": profile.get("profileName"),
        "gmailAccount": profile.get("gmailAccount"),
        "subject": profile.get("subject"),
        "templates": profile.get("templates", []),
        "reminderTemplates": profile.get("reminderTemplates", []),
        "sendingOptions": profile.get("sendingOptions"),
        "promptSettings": profile.get("promptSettings"),
    }
    
    # Store dailyLimit for this campaign
    doc["dailyLimit"] = daily_limit
    # Keep limitOverride for backward compatibility
    doc["limitOverride"] = payload.limitOverride

    result = await campaigns.insert_one(doc)
    created = await campaigns.find_one({"_id": result.inserted_id})

    # Tag all PENDING profile_emails with this campaign_id
    await profile_emails_col.update_many(
        pending_query,
        {
            "$set": {
                "campaignId": str(result.inserted_id),
                "updatedAt": datetime.now(timezone.utc),
            }
        },
    )

    await create_notification(
        employee_id=profile["employeeId"],
        message=f"Campaign '{campaign_name}' created with {pending_count} pending email(s). Daily limit: {daily_limit}",
        type=NotificationType.INFO,
    )

    return serialize_doc(created)


async def create_scheduled_campaign(
    payload,  # CampaignScheduleRequest
    employee_id: str,
    is_admin: bool,
) -> dict:
    """
    Create a campaign scheduled for future execution via Linux Cron.
    
    The campaign will not execute immediately. It will be queued and executed
    when the scheduled_for time arrives.
    """
    from app.campaigns.schema import CampaignScheduleRequest
    
    profile = await get_profile(payload.profileId, employee_id, is_admin)

    if not profile.get("isActive", False):
        raise BadRequestException(
            "Profile is not active. Activate it before scheduling a campaign."
        )

    # Count pending rows of the selected mail type.
    profile_emails_col = get_collection("profile_emails")
    pending_query = {
        "profileId": payload.profileId,
        "sendStatus": SendStatus.PENDING.value,
        **_profile_email_type_filter(payload.mailType),
    }
    pending_count = await profile_emails_col.count_documents(pending_query)

    if pending_count == 0:
        raise BadRequestException(
            f"No pending {payload.mailType} emails in this profile's list. "
            + (
                "Generate the list first or retry failed emails."
                if payload.mailType == "draft"
                else "Convert sent drafts to reminders first."
            )
        )

    # Block only another active campaign of the same type.
    campaigns = get_collection(COLLECTION)
    conflicting_campaign = await campaigns.find_one(
        {
            "profileId": payload.profileId,
            **_profile_email_type_filter(payload.mailType),
            "status": {"$in": ACTIVE_CAMPAIGN_STATUSES},
        }
    )
    if conflicting_campaign:
        raise BadRequestException(
            f"Cannot schedule {payload.mailType} campaign. This profile has an existing "
            f"{payload.mailType} campaign: '{conflicting_campaign.get('campaignName')}'\n"
            f"Status: {conflicting_campaign.get('status')}\n"
            f"Please wait for it to complete or delete it first."
        )

    # Use dailyLimit from request, default to profile's dailyLimit if not provided
    daily_limit = payload.dailyLimit or profile.get("sendingOptions", {}).get("dailyLimit", 100)

    campaign_name = (
        payload.campaignName.strip()
        or f"{profile['profileName']} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )

    # Simple approach: just store the provided time and recurrence settings
    # The scheduler will handle when to run based on recurrence type and days
    
    now = datetime.now(timezone.utc)
    
    from app.campaigns.scheduler import calculate_next_run
    utc_dt = calculate_next_run(
        recurrence_type=payload.recurrenceType,
        scheduled_time_local=payload.scheduledTimeLocal,
        timezone_offset_minutes=payload.timezoneOffsetMinutes,
        recurrence_days=payload.recurrenceDays,
        scheduled_date_local=payload.scheduledDateLocal,
        current_utc=now,
    )
    
    print(f"[SCHEDULER] Local time: {payload.scheduledTimeLocal}, offset: {payload.timezoneOffsetMinutes} min, UTC: {utc_dt.isoformat()}, Recurrence: {payload.recurrenceType}, Days: {payload.recurrenceDays}")

    # Build campaign with scheduled_for parameter
    doc = build_campaign_document(
        profile_id=payload.profileId,
        employee_id=profile["employeeId"],
        campaign_name=campaign_name,
        total_emails=pending_count,
        scheduled_for=utc_dt,  # This sets status to SCHEDULED
        mail_type=payload.mailType,
    )
    
    # Snapshot relevant profile fields for audit trail
    doc["profileSnapshot"] = {
        "profileName": profile.get("profileName"),
        "gmailAccount": profile.get("gmailAccount"),
        "subject": profile.get("subject"),
        "templates": profile.get("templates", []),
        "reminderTemplates": profile.get("reminderTemplates", []),
        "sendingOptions": profile.get("sendingOptions"),
        "promptSettings": profile.get("promptSettings"),
    }
    
    # Store dailyLimit and retry settings
    doc["dailyLimit"] = daily_limit
    doc["maxRetries"] = payload.maxRetries
    
    display_time = payload.scheduledTimeLocal
    if payload.scheduledDateLocal:
        display_time = f"{payload.scheduledDateLocal}T{payload.scheduledTimeLocal}"
    doc["scheduledForDisplay"] = display_time  # Store the display time
    
    # Store recurrence settings
    doc["recurrenceType"] = payload.recurrenceType
    doc["recurrenceDays"] = payload.recurrenceDays
    doc["recurrenceEndDate"] = payload.recurrenceEndDate
    doc["timezoneOffsetMinutes"] = payload.timezoneOffsetMinutes

    result = await campaigns.insert_one(doc)
    created = await campaigns.find_one({"_id": result.inserted_id})

    # Tag all PENDING profile_emails with this campaign_id
    await profile_emails_col.update_many(
        pending_query,
        {
            "$set": {
                "campaignId": str(result.inserted_id),
                "updatedAt": datetime.now(timezone.utc),
            }
        },
    )

    scheduled_time_str = payload.scheduledTimeLocal
    if payload.scheduledDateLocal:
        scheduled_time_str = f"{payload.scheduledDateLocal} {payload.scheduledTimeLocal}"
    await create_notification(
        employee_id=profile["employeeId"],
        message=f"Campaign '{campaign_name}' scheduled for {scheduled_time_str} with {pending_count} pending email(s). Daily limit: {daily_limit}",
        type=NotificationType.INFO,
    )

    return serialize_doc(created)


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

async def _get_campaign_owned(
    campaign_id: str, employee_id: str, is_admin: bool
) -> dict:
    campaigns = get_collection(COLLECTION)
    doc = await campaigns.find_one({"_id": to_object_id(campaign_id)})
    if not doc:
        raise NotFoundException("Campaign not found")
    if not is_admin and doc.get("employeeId") != employee_id:
        raise ForbiddenException("Access denied")
    return doc


async def set_status(
    campaign_id: str,
    new_status: CampaignStatus,
    employee_id: str,
    is_admin: bool,
) -> dict:
    doc = await _get_campaign_owned(campaign_id, employee_id, is_admin)
    current = doc.get("status")

    # Allowed transitions
    allowed: dict[str, set] = {
        CampaignStatus.PENDING.value: {CampaignStatus.RUNNING, CampaignStatus.PAUSED, CampaignStatus.FAILED},
        CampaignStatus.SCHEDULED.value: {CampaignStatus.PROCESSING, CampaignStatus.FAILED},
        CampaignStatus.PROCESSING.value: {CampaignStatus.RUNNING, CampaignStatus.PAUSED, CampaignStatus.FAILED},
        CampaignStatus.RUNNING.value: {CampaignStatus.PAUSED, CampaignStatus.COMPLETED, CampaignStatus.FAILED, CampaignStatus.SCHEDULED},
        CampaignStatus.PAUSED.value: {CampaignStatus.RUNNING, CampaignStatus.FAILED, CampaignStatus.SCHEDULED},
        CampaignStatus.COMPLETED.value: set(),
        CampaignStatus.FAILED.value: {CampaignStatus.RUNNING, CampaignStatus.SCHEDULED},
    }

    if new_status not in allowed.get(current, set()):
        raise BadRequestException(
            f"Cannot transition campaign from '{current}' to '{new_status.value}'"
        )

    now = datetime.now(timezone.utc)
    update: dict = {"status": new_status.value, "updatedAt": now}

    if new_status == CampaignStatus.RUNNING:
        if not doc.get("startedAt"):
            update["startedAt"] = now
    elif new_status == CampaignStatus.PAUSED:
        update["pausedAt"] = now
        update["pausedFromStatus"] = current
    elif new_status in (CampaignStatus.COMPLETED, CampaignStatus.FAILED):
        update["completedAt"] = now

    campaigns = get_collection(COLLECTION)
    update_operation = {"$set": update}
    if new_status in (CampaignStatus.RUNNING, CampaignStatus.SCHEDULED):
        update_operation["$unset"] = {"pausedFromStatus": ""}
    result = await campaigns.find_one_and_update(
        {"_id": to_object_id(campaign_id), "status": current},
        update_operation,
        return_document=True,
    )
    if result is None:
        raise BadRequestException("Campaign status changed while updating. Please try again.")
    return serialize_doc(result)


async def resume_campaign(
    campaign_id: str,
    employee_id: str,
    is_admin: bool,
) -> tuple[dict, bool, bool]:
    """Resume a paused execution and indicate whether it came from the scheduler."""
    doc = await _get_campaign_owned(campaign_id, employee_id, is_admin)
    if doc.get("status") != CampaignStatus.PAUSED.value:
        raise BadRequestException(
            f"Cannot resume campaign with status '{doc.get('status')}'"
        )

    scheduled_execution = (
        doc.get("processingStartedAt") is not None
        and doc.get("scheduledFor") is not None
    )
    new_status = (
        CampaignStatus.PROCESSING if scheduled_execution else CampaignStatus.RUNNING
    )
    now = datetime.now(timezone.utc)
    update: dict = {"status": new_status.value, "updatedAt": now}
    if new_status == CampaignStatus.RUNNING and not doc.get("startedAt"):
        update["startedAt"] = now

    campaigns = get_collection(COLLECTION)
    result = await campaigns.find_one_and_update(
        {
            "_id": to_object_id(campaign_id),
            "status": CampaignStatus.PAUSED.value,
        },
        {
            "$set": update,
            "$inc": {"executionGeneration": 1},
            "$unset": {"pausedFromStatus": ""},
        },
        return_document=True,
    )
    if result is None:
        raise BadRequestException("Campaign status changed while resuming. Please try again.")
    return serialize_doc(result), True, scheduled_execution


async def start_campaign_worker(campaign_id: str) -> bool:
    """Atomically start a worker only if the campaign is not paused or terminal."""
    campaigns = get_collection(COLLECTION)
    campaign_oid = to_object_id(campaign_id)
    doc = await campaigns.find_one(
        {"_id": campaign_oid},
        {"status": 1, "startedAt": 1},
    )
    if not doc:
        return False

    current = doc.get("status")
    if current == CampaignStatus.RUNNING.value:
        return True
    if current not in {
        CampaignStatus.PENDING.value,
        CampaignStatus.PROCESSING.value,
    }:
        return False

    now = datetime.now(timezone.utc)
    update: dict = {"status": CampaignStatus.RUNNING.value, "updatedAt": now}
    if not doc.get("startedAt"):
        update["startedAt"] = now

    result = await campaigns.find_one_and_update(
        {"_id": campaign_oid, "status": current},
        {"$set": update},
        return_document=True,
    )
    return result is not None


# ---------------------------------------------------------------------------
# Counter updates (called by campaign engine)
# ---------------------------------------------------------------------------

async def increment_counters(
    campaign_id: str,
    sent: int = 0,
    failed: int = 0,
    skipped: int = 0,
) -> None:
    """Atomic counter increment — called after each email send attempt."""
    campaigns = get_collection(COLLECTION)
    inc: dict = {}
    if sent:
        inc["sent"] = sent
        inc["executionSent"] = sent
    if failed:
        inc["failed"] = failed
    if skipped:
        inc["skipped"] = skipped
    if inc:
        inc["pending"] = -(sent + failed + skipped)
        await campaigns.update_one(
            {"_id": to_object_id(campaign_id)},
            {"$inc": inc, "$set": {"updatedAt": datetime.now(timezone.utc)}},
        )


async def finalize_campaign(campaign_id: str) -> None:
    """
    Mark campaign COMPLETED and push a final notification.
    Called by the engine when the send loop exhausts all pending emails.
    """
    campaigns = get_collection(COLLECTION)
    doc = await campaigns.find_one({"_id": to_object_id(campaign_id)})
    if not doc:
        return

    now = datetime.now(timezone.utc)
    update_result = await campaigns.update_one(
        {
            "_id": to_object_id(campaign_id),
            "status": {
                "$in": [
                    CampaignStatus.RUNNING.value,
                    CampaignStatus.PROCESSING.value,
                ]
            },
        },
        {
            "$set": {
                "status": CampaignStatus.COMPLETED.value,
                "completedAt": now,
                "updatedAt": now,
                "pending": 0,
            }
        },
    )
    if update_result.modified_count == 0:
        return

    # Also log completion
    from app.logs.model import LogAction, build_log_document
    logs = get_collection("logs")
    await logs.insert_one(
        build_log_document(
            employee_id=doc["employeeId"],
            profile_id=doc["profileId"],
            action=LogAction.CAMPAIGN_COMPLETED,
            sent_count=doc.get("sent", 0),
            run_date=now,
        )
    )

    await create_notification(
        employee_id=doc["employeeId"],
        message=(
            f"Campaign '{doc['campaignName']}' completed. "
            f"Sent: {doc.get('sent', 0)}, "
            f"Failed: {doc.get('failed', 0)}."
        ),
        type=NotificationType.SUCCESS,
    )


async def abort_campaign(campaign_id: str, reason: str = "") -> None:
    """Mark campaign FAILED — called when the engine hits an unrecoverable error."""
    campaigns = get_collection(COLLECTION)
    doc = await campaigns.find_one({"_id": to_object_id(campaign_id)})
    if not doc:
        return

    now = datetime.now(timezone.utc)
    await campaigns.update_one(
        {"_id": to_object_id(campaign_id)},
        {
            "$set": {
                "status": CampaignStatus.FAILED.value,
                "errorMessage": reason,
                "completedAt": now,
                "updatedAt": now,
            }
        },
    )

    await create_notification(
        employee_id=doc["employeeId"],
        message=f"Campaign '{doc['campaignName']}' failed. {reason}".strip(),
        type=NotificationType.ERROR,
    )


async def is_worker_active(campaign_id: str) -> bool:
    """Return whether a worker may continue sending for this campaign."""
    campaigns = get_collection(COLLECTION)
    doc = await campaigns.find_one(
        {"_id": to_object_id(campaign_id)}, {"status": 1}
    )
    return doc is not None and doc.get("status") in {
        CampaignStatus.RUNNING.value,
        CampaignStatus.PROCESSING.value,
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def list_campaigns(
    employee_id: str | list[str] | None,
    params: PaginationParams,
    status_filter: str | None = None,
    profile_id: str | None = None,
) -> dict:
    campaigns = get_collection(COLLECTION)
    query: dict = {}

    if employee_id is not None:
        if isinstance(employee_id, list):
            query["employeeId"] = {"$in": employee_id}
        else:
            query["employeeId"] = employee_id
    normalized_status = status_filter.strip().lower() if status_filter else ""
    if normalized_status and normalized_status not in {"all", "1"}:
        query["status"] = normalized_status
    if profile_id:
        query["profileId"] = profile_id

    total = await campaigns.count_documents(query)
    cursor = (
        campaigns.find(query)
        .sort("createdAt", -1)
        .skip(params.skip)
        .limit(params.pageSize)
    )
    docs = [_add_campaign_progress(doc) async for doc in cursor]
    return build_paginated_response(docs, total, params)


async def get_campaign(
    campaign_id: str, employee_id: str, is_admin: bool
) -> dict:
    doc = await _get_campaign_owned(campaign_id, employee_id, is_admin)
    return _add_campaign_progress(doc)


async def update_daily_limit(
    campaign_id: str,
    new_daily_limit: int,
    employee_id: str,
    is_admin: bool,
) -> dict:
    """
    Update the daily limit for a campaign.
    Can be called while campaign is paused or running.
    
    Args:
        campaign_id: Campaign to update
        new_daily_limit: New daily limit (1-10000)
        employee_id: Current user's employee ID
        is_admin: Whether current user is admin
        
    Returns:
        Updated campaign document
        
    Raises:
        ForbiddenException: If not owner/admin
        NotFoundException: If campaign not found
    """
    doc = await _get_campaign_owned(campaign_id, employee_id, is_admin)
    
    campaigns = get_collection(COLLECTION)
    result = await campaigns.find_one_and_update(
        {"_id": to_object_id(campaign_id)},
        {"$set": {
            "dailyLimit": new_daily_limit,
            "updatedAt": datetime.now(timezone.utc)
        }},
        return_document=True,
    )
    
    await create_notification(
        employee_id=doc["employeeId"],
        message=f"Campaign '{doc['campaignName']}' daily limit updated to {new_daily_limit}.",
        type=NotificationType.INFO,
    )
    
    return serialize_doc(result)


async def delete_campaign(
    campaign_id: str, employee_id: str, is_admin: bool
) -> None:
    """
    Delete a campaign.
    
    Can only delete campaigns that are not RUNNING.
    Deleting a campaign also cleans up associated profile_emails.
    
    Args:
        campaign_id: Campaign to delete
        employee_id: Current user's employee ID
        is_admin: Whether current user is admin
        
    Raises:
        ForbiddenException: If not owner/admin
        BadRequestException: If campaign is RUNNING
    """
    doc = await _get_campaign_owned(campaign_id, employee_id, is_admin)
    
    # Processing campaigns may already have a scheduled worker in flight.
    if doc.get("status") in {
        CampaignStatus.RUNNING.value,
        CampaignStatus.PROCESSING.value,
    }:
        raise BadRequestException(
            "Cannot delete an active campaign. Pause it first."
        )
    
    campaigns = get_collection(COLLECTION)
    await campaigns.delete_one({"_id": to_object_id(campaign_id)})
    
    # Also clean up associated profile_emails (optional - keep for audit trail)
    # You can choose to keep them for history, or delete them
    # profile_emails_col = get_collection("profile_emails")
    # await profile_emails_col.delete_many({"campaignId": campaign_id})
    
    await create_notification(
        employee_id=doc["employeeId"],
        message=f"Campaign '{doc['campaignName']}' has been deleted.",
        type=NotificationType.INFO,
    )
