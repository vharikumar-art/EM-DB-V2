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
        
        # Check today first
        if current_weekday in recurrence_days:
            candidate = local_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if candidate > local_now:
                local_next = candidate
            else:
                # Need a future day. Find the next day in the list.
                days_ahead = min((day - current_weekday) % 7 if (day - current_weekday) % 7 != 0 else 7 for day in recurrence_days)
                local_next = local_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0) + timedelta(days=days_ahead)
        else:
            # Find the next day in the list.
            days_ahead = min((day - current_weekday) % 7 for day in recurrence_days if (day - current_weekday) % 7 > 0)
            local_next = local_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    else:
        raise ValueError(f"Unknown recurrence_type: {recurrence_type}")
        
    # Convert local_next back to UTC
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
            "total_executed": self.total_executed,
            "successful": self.successful,
            "failed": self.failed,
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
    
    print(f"[SCHEDULER DEBUG] find_due_campaigns - current time: {now.isoformat()}")
    
    query = {
        "status": CampaignStatus.SCHEDULED.value,
        "scheduledFor": {"$lte": now}
    }
    
    due_campaigns = await campaigns.find(query).to_list(length=None)
    print(f"[SCHEDULER DEBUG] Found {len(due_campaigns)} due campaigns")
    for c in due_campaigns:
        print(f"[SCHEDULER DEBUG] Campaign: {c.get('campaignName')} - scheduled for {c.get('scheduledFor')}")
    
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
            }
        },
        return_document=False,  # Return the document before update
    )
    
    return result is not None


async def execute_campaign(campaign_id: str) -> tuple[bool, Optional[str]]:
    """
    Execute a campaign using the existing run_campaign() function.
    
    Returns:
        tuple: (success: bool, error_message: Optional[str])
    """
    try:
        campaigns = get_collection(COLLECTION)
        campaign = await campaigns.find_one({"_id": to_object_id(campaign_id)})
        
        if not campaign:
            return False, "Campaign not found"
        
        # Call the existing campaign execution logic
        await run_campaign(campaign_id)
        
        return True, None
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Campaign {campaign_id} execution failed: {error_msg}", exc_info=True)
        return False, error_msg


async def finalize_campaign_execution(
    campaign_id: str,
    success: bool,
    error_message: Optional[str] = None
) -> None:
    """
    Update campaign status after execution attempt.
    
    If success: status = completed
    If failure: status = scheduled (for retry), increment retryCount
    """
    campaigns = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    campaign = await campaigns.find_one({"_id": to_object_id(campaign_id)})
    
    if not campaign:
        return
    
    processing_started = campaign.get("processingStartedAt")
    execution_duration = None
    
    if processing_started:
        duration = now - processing_started
        execution_duration = duration.total_seconds()
    
    if success:
        # Check if it should reschedule
        recurrence_type = campaign.get("recurrenceType", "once")
        if recurrence_type in ["daily", "weekly"]:
            try:
                # Calculate next run time
                # We need the local time string from scheduledForDisplay (e.g. '2026-07-23T09:00' or just '09:00')
                display_str = campaign.get("scheduledForDisplay", "00:00")
                time_str = display_str.split("T")[-1] if "T" in display_str else display_str[-5:]
                
                next_run = calculate_next_run(
                    recurrence_type=recurrence_type,
                    scheduled_time_local=time_str,
                    timezone_offset_minutes=0, # Simplification: assume server UTC if offset not available, or extract it if stored
                    recurrence_days=campaign.get("recurrenceDays", []),
                )
                
                # Reschedule the campaign
                await campaigns.update_one(
                    {"_id": to_object_id(campaign_id)},
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
                
                await create_notification(
                    employee_id=campaign.get("employeeId"),
                    message=f"Campaign '{campaign['campaignName']}' finished current batch and is scheduled for next run at {next_run.strftime('%Y-%m-%d %H:%M')} UTC.",
                    type=NotificationType.INFO,
                )
                return
            except Exception as e:
                logger.error(f"Failed to calculate next run for campaign {campaign_id}: {e}", exc_info=True)
                # Fall through to standard completion if rescheduling fails
        
        # Standard completion (once, or rescheduling failed)
        await campaigns.update_one(
            {"_id": to_object_id(campaign_id)},
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
        
        # Send success notification
        await create_notification(
            employee_id=campaign.get("employeeId"),
            message=f"Scheduled campaign '{campaign['campaignName']}' completed successfully.",
            type=NotificationType.SUCCESS,
        )
    
    else:
        # Campaign failed
        retry_count = campaign.get("retryCount", 0)
        max_retries = campaign.get("maxRetries", 3)
        
        if retry_count < max_retries:
            # Retry later - reset to scheduled status
            retry_count += 1
            next_retry = now + timedelta(minutes=5)  # Retry in 5 minutes
            
            await campaigns.update_one(
                {"_id": to_object_id(campaign_id)},
                {
                    "$set": {
                        "status": CampaignStatus.SCHEDULED.value,
                        "scheduledFor": next_retry,
                        "retryCount": retry_count,
                        "executionDuration": execution_duration,
                        "errorMessage": error_message,
                        "updatedAt": now,
                    }
                }
            )
            
            # Send retry notification
            await create_notification(
                employee_id=campaign.get("employeeId"),
                message=f"Campaign '{campaign['campaignName']}' failed. Retrying in 5 minutes (attempt {retry_count}/{max_retries}).",
                type=NotificationType.WARNING,
            )
        
        else:
            # Max retries exceeded - mark as failed
            await campaigns.update_one(
                {"_id": to_object_id(campaign_id)},
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
            
            # Send failure notification
            await create_notification(
                employee_id=campaign.get("employeeId"),
                message=f"Campaign '{campaign['campaignName']}' failed after {max_retries} attempts. Error: {error_message}",
                type=NotificationType.ERROR,
            )


async def process_scheduled_campaigns() -> dict:
    """
    Main scheduler function called by cron every minute.
    
    1. Finds all campaigns due for execution
    2. For each campaign:
        a. Atomically transitions to 'processing' status
        b. Executes the campaign
        c. Updates status to 'completed' or 'scheduled' (for retry)
    3. Returns execution summary
    
    Returns:
        dict: Execution result containing counts and details
    """
    result = SchedulerResult()
    
    try:
        logger.info("Starting scheduled campaign processing")
        
        # Find all campaigns due for execution
        due_campaigns = await find_due_campaigns()
        result.total_checked = len(due_campaigns)
        
        if not due_campaigns:
            logger.info("No campaigns due for execution")
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
                
                logger.info(f"Processing campaign: {campaign_name} ({campaign_id})")
                result.total_executed += 1
                
                # Execute the campaign
                success, error_msg = await execute_campaign(campaign_id)
                
                # Finalize based on result
                await finalize_campaign_execution(campaign_id, success, error_msg)
                
                if success:
                    result.successful += 1
                    logger.info(f"Campaign {campaign_id} completed successfully")
                else:
                    result.failed += 1
                    logger.error(f"Campaign {campaign_id} failed: {error_msg}")
                    result.errors.append({
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_name,
                        "error": error_msg,
                    })
            
            except Exception as e:
                result.failed += 1
                error_msg = str(e)
                logger.error(f"Unexpected error processing campaign {campaign_id}: {error_msg}", exc_info=True)
                
                # Still finalize the campaign to avoid stuck state
                await finalize_campaign_execution(campaign_id, False, error_msg)
                
                result.errors.append({
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "error": error_msg,
                })
        
        logger.info(
            f"Scheduler completed: {result.successful} successful, "
            f"{result.failed} failed out of {result.total_executed} executed"
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
