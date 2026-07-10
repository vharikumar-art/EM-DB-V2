from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CampaignStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


def build_campaign_document(
    profile_id: str,
    employee_id: str,
    campaign_name: str,
    total_emails: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "campaignName": campaign_name,
        "profileId": profile_id,
        "employeeId": employee_id,
        "status": CampaignStatus.PENDING.value,
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
    }
