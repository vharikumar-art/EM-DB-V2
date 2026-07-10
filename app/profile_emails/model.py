from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SendStatus(str, Enum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


def build_profile_email_document(
    profile_id: str,
    employee_id: str,
    master_email_id: str,
    record: dict[str, Any],
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """
    Working copy of an email_master record scoped to a profile.
    Only this document is mutated during campaigns — email_master is never touched.
    """
    now = datetime.now(timezone.utc)
    return {
        "profileId": profile_id,
        "employeeId": employee_id,
        "campaignId": campaign_id,
        "masterEmailId": master_email_id,
        # Denormalized contact fields (snapshot at generation time)
        "fullName": record.get("fullName", ""),
        "email": record["email"],
        "company": record.get("company", ""),
        "website": record.get("website", ""),
        "country": record.get("country", ""),
        "state": record.get("state", ""),
        "city": record.get("city", ""),
        "domain": record.get("domain", ""),
        "industry": record.get("industry", ""),
        "designation": record.get("designation", ""),
        "phone": record.get("phone", ""),
        "linkedin": record.get("linkedin", ""),
        # Campaign tracking
        "sendStatus": SendStatus.PENDING.value,
        "threadId": None,
        "messageId": None,
        "sentDate": None,
        "errorMessage": None,
        "notes": "",
        "retryCount": 0,
        "createdAt": now,
        "updatedAt": now,
    }
