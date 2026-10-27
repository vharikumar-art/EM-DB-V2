"""
Campaign Scheduler Service

Handles time-based campaign scheduling via Linux Cron.
Finds due campaigns, manages atomic status transitions, and executes them.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.campaigns.model import CampaignStatus
from app.campaign_engine.worker import run_campaign
from app.database.mongodb import get_collection
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.utils.response import serialize_doc, serialize_list, to_object_id

logger = logging.getLogger(__name__)
COLLECTION = "campaigns"


def calculate_next_run(
    recurrence_type: str,
    scheduled_time_local: str,  # format HH:MM
    timezone_offset_minutes: int,
    recurrence_days: list[int] = None,
    scheduled_date_local: str = None,  # format YYYY-MM-DD
    current_utc: datetime = None
) -> datetime:
    """
    Calculate the next UTC datetime a campaign should run.
    """
    if current_utc is None:
        current_utc = datetime.now(timezone.utc)
        
    # User's local time right now
    local_now = current_utc - timedelta(minutes=timezone_offset_minutes)
    
    # Parse the target time
    target_hour, target_minute = map(int, scheduled_time_local.split(':'))
    
    if recurrence_type == "once":
        if not scheduled_date_local:
            raise ValueError("scheduledDateLocal is required for 'once' campaigns")
        target_year, target_month, target_day = map(int, scheduled_date_local.split('-'))
        local_next = local_now.replace(
            year=target_year, month=target_month, day=target_day,
            hour=target_hour, minute=target_minute, second=0, microsecond=0
        )
    elif recurrence_type == "daily":
        local_next = local_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if local_next <= local_now:
            local_next += timedelta(days=1)
    elif recurrence_type == "weekly":
        if not recurrence_days:
            raise ValueError("recurrenceDays is required for 'weekly' campaigns")

        # Current local weekday (0=Mon, 6=Sun)
        current_weekday = local_now.weekday()

        # Scan up to 7 days ahead to find the next valid day+time in the future
        local_next = None
        for days_ahead in range(8):  # 0 = today, 7 = same day next week
            candidate_day = (current_weekday + days_ahead) % 7
            if candidate_day in recurrence_days:
                candidate = (
                    local_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                    + timedelta(days=days_ahead)
                )
                if candidate > local_now:
                    local_next = candidate
                    break

        if local_next is None:
            # Fallback: next occurrence in 7 days (should never happen)
            local_next = (
                local_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                + timedelta(days=7)
            )
    else:
        raise ValueError(f"Unknown recurrence_type: {recurrence_type}")
        
    # Convert local_next back to UTC.
    # Browser sends getTimezoneOffset() which for IST (UTC+5:30) = -330.
    # local_now = UTC - (-330) = UTC + 330  ✓
    # utc_next  = local_next + (-330) = local_next - 330  ✓
    utc_next = local_next.replace(tzinfo=timezone.utc) + timedelta(minutes=timezone_offset_minutes)
    return utc_next


class SchedulerResult:
    """Result of a scheduler run"""
    def __init__(self):
        self.total_checked = 0
        self.total_executed = 0
        self.successful = 0
        self.failed = 0
        self.errors: list[dict] = []
        self.execution_start = datetime.now(timezone.utc)
        self.execution_end = None
    
    def get_duration_ms(self) -> float:
        """Get execution duration in milliseconds"""
        if self.execution_end:
            delta = self.execution_end - self.execution_start
            return delta.total_seconds() * 1000
        return 0
    
    def to_dict(self) -> dict:
        """Convert result to dictionary"""
        return {
            "total_checked": self.total_checked,
            "total_dispatched": self.total_executed,
            "successful_sync": self.successful,
            "failed_sync": self.failed,
            "errors": self.errors,
            "execution_duration_ms": self.get_duration_ms(),
            "execution_start": self.execution_start.isoformat(),
            "execution_end": self.execution_end.isoformat() if self.execution_end else None,
        }


async def find_due_campaigns() -> list[dict]:
    """
    Find all campaigns that are due for execution.
    
    Returns campaigns where:
    - status = "scheduled"
    - scheduledFor <= current_time
    - retryCount < maxRetries (or has max retries but failed)
    """
    campaigns = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    
    #print(f"[SCHEDULER DEBUG] find_due_campaigns - current time: {now.isoformat()}")
    
    query = {
        "status": CampaignStatus.SCHEDULED.value,
        "scheduledFor": {"$lte": now}
    }
    
    due_campaigns = await campaigns.find(query).to_list(length=None)
    #print(f"[SCHEDULER DEBUG] Found {len(due_campaigns)} due campaigns")
    #for c in due_campaigns:
    #    print(f"[SCHEDULER DEBUG] Campaign: {c.get('campaignName')} - scheduled for {c.get('scheduledFor')}")
    
    return due_campaigns


async def transition_to_processing(campaign_id: str) -> bool:
    """
    Atomically transition campaign from 'scheduled' to 'processing'.
    
    Returns True if transition succeeded (only one process should succeed).
    Returns False if another process already transitioned this campaign.
    
    This prevents duplicate execution.
    """
    campaigns = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    
    # Atomic operation: only update if current status is 'scheduled'
    result = await campaigns.find_one_and_update(
        {
            "_id": to_object_id(campaign_id),
            "status": CampaignStatus.SCHEDULED.value
        },
        {
            "$set": {
                "status": CampaignStatus.PROCESSING.value,
                "processingStartedAt": now,
                "updatedAt": now,
                "executionSent": 0,
            },
            "$inc": {"executionGeneration": 1},
        },
        return_document=False,  # Return the document before update
    )
    
    return result is not None


async def execute_campaign(
    campaign_id: str,
) -> tuple[bool | None, Optional[str]]:
    """
    Execute a campaign using the existing run_campaign() function.
    
    Returns:
        A missing success value means the worker lock is held by another task.
    """
    try:
        campaigns = get_collection(COLLECTION)
        campaign = await campaigns.find_one({"_id": to_object_id(campaign_id)})
        
        if not campaign:
            return False, "Campaign not found"
        
        # Call the existing campaign execution logic
        worker_started = await run_campaign(campaign_id)
        if worker_started is False:
            return None, None
        
        return True, None
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Campaign {campaign_id} execution failed: {error_msg}", exc_info=True)
        return False, error_msg


async def finalize_campaign_execution(
    campaign_id: str,
    success: bool,
    error_message: Optional[str] = None,
    execution_generation: int | None = None,
) -> None:
    """
    Update campaign status after execution attempt.
    
    Successful runs complete or reschedule recurring campaigns. Failures are terminal.
    """
    campaigns = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    campaign = await campaigns.find_one({"_id": to_object_id(campaign_id)})
    
    if not campaign:
        return
    if (
        execution_generation is not None
        and campaign.get("executionGeneration") != execution_generation
    ):
        return

    generation_filter = (
        {"executionGeneration": execution_generation}
        if execution_generation is not None
        else {}
    )
    
    processing_started = campaign.get("processingStartedAt")
    execution_duration = None
    
    if processing_started:
        # MongoDB returns naive datetimes (UTC); make aware before subtracting
        if processing_started.tzinfo is None:
            processing_started = processing_started.replace(tzinfo=timezone.utc)
        duration = now - processing_started
        execution_duration = duration.total_seconds()
    
    current_status = campaign.get("status")

    if success:
        # Check actual status set by worker
        if current_status == CampaignStatus.FAILED.value:
            # Worker aborted it (auth failed, templates missing, etc.)
            success = False
            error_message = campaign.get("errorMessage") or "Aborted by worker"
        elif current_status == CampaignStatus.PAUSED.value:
            await campaigns.update_one(
                {
                    "_id": to_object_id(campaign_id),
                    "status": CampaignStatus.PAUSED.value,
                    **generation_filter,
                },
                {"$set": {"executionDuration": execution_duration}}
            )
            return

    if success:
        # Check if it should reschedule.
        recurrence_type = campaign.get("recurrenceType", "once")
        if recurrence_type in ["daily", "weekly"]:
            if campaign.get("pending", 0) == 0:
                update_result = await campaigns.update_one(
                    {
                        "_id": to_object_id(campaign_id),
                        **generation_filter,
                        "status": {"$in": [
                            CampaignStatus.PROCESSING.value,
                            CampaignStatus.RUNNING.value,
                        ]},
                    },
                    {
                        "$set": {
                            "status": CampaignStatus.COMPLETED.value,
                            "completedAt": now,
                            "executionDuration": execution_duration,
                            "updatedAt": now,
                            "errorMessage": None,
                        }
                    }
                )
                if update_result.modified_count == 0:
                    return
                await create_notification(
                    employee_id=campaign.get("employeeId"),
                    message=f"Campaign '{campaign['campaignName']}' completed because all pending emails have been sent.",
                    type=NotificationType.SUCCESS,
                )
                return

            try:
                # Daily/weekly campaigns continue to the next scheduled run while
                # there are still pending emails remaining in the profile queue.
                display_str = campaign.get("scheduledForDisplay", "00:00")
                time_str = display_str.split("T")[-1] if "T" in display_str else display_str[-5:]

                next_run = calculate_next_run(
                    recurrence_type=recurrence_type,
                    scheduled_time_local=time_str,
                    timezone_offset_minutes=campaign.get("timezoneOffsetMinutes", 0),
                    recurrence_days=campaign.get("recurrenceDays", []),
                )

                update_result = await campaigns.update_one(
                    {
                        "_id": to_object_id(campaign_id),
                        **generation_filter,
                        "status": {"$in": [
                            CampaignStatus.PROCESSING.value,
                            CampaignStatus.RUNNING.value,
                        ]},
                    },
                    {
                        "$set": {
                            "status": CampaignStatus.SCHEDULED.value,
                            "scheduledFor": next_run,
                            "executionDuration": execution_duration,
                            "updatedAt": now,
                            "errorMessage": None,
                        }
                    }
                )
                if update_result.modified_count == 0:
                    return

                await create_notification(
                    employee_id=campaign.get("employeeId"),
                    message=f"Campaign '{campaign['campaignName']}' completed this run and is scheduled for next occurrence at {next_run.strftime('%Y-%m-%d %H:%M')} UTC.",
                    type=NotificationType.INFO,
                )
                return
            except Exception as e:
                logger.error(f"Failed to calculate next run for campaign {campaign_id}: {e}", exc_info=True)
                # Fall through to standard completion if rescheduling fails
        
        # Standard completion (once, or rescheduling failed)
        update_result = await campaigns.update_one(
            {
                "_id": to_object_id(campaign_id),
                **generation_filter,
                "status": {"$in": [
                    CampaignStatus.PROCESSING.value,
                    CampaignStatus.RUNNING.value,
                ]},
            },
            {
                "$set": {
                    "status": CampaignStatus.COMPLETED.value,
                    "completedAt": now,
                    "executionDuration": execution_duration,
                    "updatedAt": now,
                    "errorMessage": None,
                }
            }
        )
        if update_result.modified_count == 0:
            return
        
        # Send success notification
        await create_notification(
            employee_id=campaign.get("employeeId"),
            message=f"Scheduled campaign '{campaign['campaignName']}' completed successfully.",
            type=NotificationType.SUCCESS,
        )
    
    else:
        # Campaign failed
        error_message = error_message or campaign.get("errorMessage") or "Campaign execution failed"
        update_result = await campaigns.update_one(
            {
                "_id": to_object_id(campaign_id),
                **generation_filter,
                "status": {"$in": [
                    CampaignStatus.PROCESSING.value,
                    CampaignStatus.RUNNING.value,
                    CampaignStatus.SCHEDULED.value,
                ]},
            },
            {
                "$set": {
                    "status": CampaignStatus.FAILED.value,
                    "completedAt": now,
                    "executionDuration": execution_duration,
                    "errorMessage": error_message,
                    "updatedAt": now,
                }
            }
        )
        if update_result.modified_count == 0:
            return

        await create_notification(
            employee_id=campaign.get("employeeId"),
            message=f"Campaign '{campaign['campaignName']}' failed. Error: {error_message}",
            type=NotificationType.ERROR,
        )


async def _execute_and_finalize(
    campaign_id: str,
    campaign_name: str,
    execution_generation: int | None = None,
) -> None:
    """Wrapper to run a campaign in the background and finalize it upon completion."""
    try:
        campaigns = get_collection(COLLECTION)
        if execution_generation is None:
            campaign = await campaigns.find_one(
                {"_id": to_object_id(campaign_id)},
                {"executionGeneration": 1},
            )
            if not campaign:
                return
            execution_generation = campaign.get("executionGeneration")

        retry_delay = 0.1
        while True:
            campaign = await campaigns.find_one(
                {"_id": to_object_id(campaign_id)},
                {"status": 1, "executionGeneration": 1},
            )
            if (
                not campaign
                or campaign.get("status") != CampaignStatus.PROCESSING.value
                or campaign.get("executionGeneration") != execution_generation
            ):
                return

            success, error_msg = await execute_campaign(campaign_id)
            if success is None:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 2.0)
                continue
            break

        await finalize_campaign_execution(
            campaign_id, success, error_msg, execution_generation
        )
        if success:
            logger.info(f"Scheduled campaign {campaign_id} completed successfully")
        else:
            logger.error(f"Scheduled campaign {campaign_id} failed: {error_msg}")
    except Exception as e:
        logger.error(f"Fatal error in background execution for {campaign_id}: {e}", exc_info=True)
        # Fallback finalize
        try:
            await finalize_campaign_execution(
                campaign_id, False, str(e), execution_generation
            )
        except Exception:
            pass


async def process_scheduled_campaigns() -> dict:
    """
    Main scheduler function called by cron every minute.
    
    1. Finds all campaigns due for execution
    2. For each campaign:
        a. Atomically transitions to 'processing' status
        b. Dispatches the campaign to run in the background (asyncio.create_task)
    3. Returns execution summary (dispatched count)
    
    Returns:
        dict: Execution result containing counts and details
    """
    result = SchedulerResult()
    
    try:
        logger.debug("Starting scheduled campaign processing")
        
        # Find all campaigns due for execution
        due_campaigns = await find_due_campaigns()
        result.total_checked = len(due_campaigns)
        
        if not due_campaigns:
            logger.debug("No campaigns due for execution")
            result.execution_end = datetime.now(timezone.utc)
            return result.to_dict()
        
        logger.info(f"Found {len(due_campaigns)} campaigns due for execution")
        
        # Process each campaign
        for campaign in due_campaigns:
            campaign_id = str(campaign["_id"])
            campaign_name = campaign.get("campaignName", "Unknown")
            
            try:
                # Atomic transition to processing
                transition_ok = await transition_to_processing(campaign_id)
                
                if not transition_ok:
                    logger.warning(f"Campaign {campaign_id} already being processed by another scheduler instance")
                    continue
                
                logger.info(f"Dispatching campaign: {campaign_name} ({campaign_id})")
                result.total_executed += 1
                
                # Execute the campaign in the background so we don't block the scheduler
                asyncio.create_task(_execute_and_finalize(campaign_id, campaign_name))
            
            except Exception as e:
                result.failed += 1
                error_msg = str(e)
                logger.error(f"Unexpected error dispatching campaign {campaign_id}: {error_msg}", exc_info=True)
                
                # Finalize the campaign to avoid stuck state
                await finalize_campaign_execution(campaign_id, False, error_msg)
                
                result.errors.append({
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "error": error_msg,
                })
        
        logger.info(
            f"Scheduler completed: {result.total_executed} campaigns dispatched to background."
        )
    
    except Exception as e:
        logger.error(f"Fatal scheduler error: {str(e)}", exc_info=True)
        result.errors.append({
            "campaign_id": None,
            "error": f"Fatal scheduler error: {str(e)}",
        })
    
    finally:
        result.execution_end = datetime.now(timezone.utc)
    
    return result.to_dict()


async def get_scheduler_status() -> dict:
    """
    Get current scheduler status for monitoring.
    
    Returns info about:
    - Number of campaigns awaiting execution
    - Number of campaigns currently processing
    - Last execution time (from logs or history)
    """
    campaigns = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    
    # Count campaigns awaiting execution
    awaiting = await campaigns.count_documents({
        "status": CampaignStatus.SCHEDULED.value,
        "scheduledFor": {"$lte": now}
    })
    
    # Count campaigns currently processing
    processing = await campaigns.count_documents({
        "status": CampaignStatus.PROCESSING.value
    })
    
    # Get recently completed campaigns (last 24 hours)
    yesterday = now - timedelta(days=1)
    recently_completed = await campaigns.count_documents({
        "status": CampaignStatus.COMPLETED.value,
        "completedAt": {"$gte": yesterday}
    })
    
    # Get recent failures
    recent_failures = await campaigns.count_documents({
        "status": CampaignStatus.FAILED.value,
        "completedAt": {"$gte": yesterday}
    })
    
    return {
        "current_time": now.isoformat(),
        "campaigns_awaiting_execution": awaiting,
        "campaigns_currently_processing": processing,
        "campaigns_completed_24h": recently_completed,
        "campaigns_failed_24h": recent_failures,
        "health": "healthy" if processing < 10 else "warning" if processing < 50 else "critical",
    }
