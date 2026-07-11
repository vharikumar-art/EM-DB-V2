from datetime import datetime, timezone

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

    # Count how many PENDING rows exist in profile_emails for this profile
    profile_emails_col = get_collection("profile_emails")
    pending_count = await profile_emails_col.count_documents(
        {"profileId": payload.profileId, "sendStatus": SendStatus.PENDING.value}
    )

    if pending_count == 0:
        raise BadRequestException(
            "No pending emails in this profile's list. "
            "Generate the list first or retry failed emails."
        )

    # Block if there's already a running campaign for this profile
    campaigns = get_collection(COLLECTION)
    running = await campaigns.find_one(
        {"profileId": payload.profileId, "status": CampaignStatus.RUNNING.value}
    )
    if running:
        raise BadRequestException(
            "A campaign is already running for this profile. "
            "Pause or complete it before starting a new one."
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
    )
    # Snapshot relevant profile fields for audit trail
    doc["profileSnapshot"] = {
        "profileName": profile.get("profileName"),
        "gmailAccount": profile.get("gmailAccount"),
        "subject": profile.get("subject"),
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
        {"profileId": payload.profileId, "sendStatus": SendStatus.PENDING.value},
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
        CampaignStatus.PENDING.value: {CampaignStatus.RUNNING, CampaignStatus.FAILED},
        CampaignStatus.RUNNING.value: {CampaignStatus.PAUSED, CampaignStatus.COMPLETED, CampaignStatus.FAILED},
        CampaignStatus.PAUSED.value: {CampaignStatus.RUNNING, CampaignStatus.FAILED},
        CampaignStatus.COMPLETED.value: set(),
        CampaignStatus.FAILED.value: {CampaignStatus.RUNNING},
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
    elif new_status in (CampaignStatus.COMPLETED, CampaignStatus.FAILED):
        update["completedAt"] = now

    campaigns = get_collection(COLLECTION)
    result = await campaigns.find_one_and_update(
        {"_id": to_object_id(campaign_id)},
        {"$set": update},
        return_document=True,
    )
    return serialize_doc(result)


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
    await campaigns.update_one(
        {"_id": to_object_id(campaign_id)},
        {
            "$set": {
                "status": CampaignStatus.COMPLETED.value,
                "completedAt": now,
                "updatedAt": now,
                "pending": 0,
            }
        },
    )

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


async def is_paused(campaign_id: str) -> bool:
    """Quick check used by the engine send loop to respect pause requests."""
    campaigns = get_collection(COLLECTION)
    doc = await campaigns.find_one(
        {"_id": to_object_id(campaign_id)}, {"status": 1}
    )
    return doc is not None and doc.get("status") == CampaignStatus.PAUSED.value


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def list_campaigns(
    employee_id: str | None,
    params: PaginationParams,
    status_filter: str | None = None,
    profile_id: str | None = None,
) -> dict:
    campaigns = get_collection(COLLECTION)
    query: dict = {}

    if employee_id:
        query["employeeId"] = employee_id
    if status_filter:
        query["status"] = status_filter
    if profile_id:
        query["profileId"] = profile_id

    total = await campaigns.count_documents(query)
    cursor = (
        campaigns.find(query)
        .sort("createdAt", -1)
        .skip(params.skip)
        .limit(params.pageSize)
    )
    docs = serialize_list([d async for d in cursor])
    return build_paginated_response(docs, total, params)


async def get_campaign(
    campaign_id: str, employee_id: str, is_admin: bool
) -> dict:
    doc = await _get_campaign_owned(campaign_id, employee_id, is_admin)
    return serialize_doc(doc)


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
    
    # Don't allow deletion of running campaigns
    if doc.get("status") == CampaignStatus.RUNNING.value:
        raise BadRequestException(
            "Cannot delete a running campaign. Pause it first."
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
