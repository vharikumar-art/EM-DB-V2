from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CampaignStatus(str, Enum):
    # Immediate execution statuses
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_MAILS = "waiting_for_mails"
    # Scheduled execution statuses
    SCHEDULED = "scheduled"
    PROCESSING = "processing"


def build_campaign_document(
    profile_id: str,
    employee_id: str,
    campaign_name: str,
    total_emails: int,
    scheduled_for: datetime | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    
    # Determine initial status based on whether campaign is scheduled
    initial_status = CampaignStatus.SCHEDULED.value if scheduled_for else CampaignStatus.PENDING.value
    
    return {
        "campaignName": campaign_name,
        "profileId": profile_id,
        "employeeId": employee_id,
        "status": initial_status,
        # Counters — updated in real-time during the send loop
        "totalEmails": total_emails,
        "pending": total_emails,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "replies": 0,
        # Timestamps
        "startedAt": None,
        "completedAt": None,
        "pausedAt": None,
        "createdAt": now,
        "updatedAt": now,
        # Snapshot of profile settings at launch time (for audit / replay)
        "profileSnapshot": {},
        # Scheduling fields
        "scheduledFor": scheduled_for,  # UTC datetime when campaign should run
        "processingStartedAt": None,  # When scheduler started processing this campaign
        "executionDuration": None,  # Seconds taken to execute (processingEndedAt - processingStartedAt)
        "errorMessage": None,  # Error details if campaign failed
        "retryCount": 0,  # Number of times this campaign has been retried
        "maxRetries": 3,  # Maximum retry attempts
    }

