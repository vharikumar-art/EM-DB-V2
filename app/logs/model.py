from datetime import datetime, timezone
from enum import Enum
from typing import Any


class LogAction(str, Enum):
    UPLOAD = "UPLOAD"
    PROFILE_UPDATED = "PROFILE_UPDATED"
    CAMPAIGN_STARTED = "CAMPAIGN_STARTED"
    CAMPAIGN_COMPLETED = "CAMPAIGN_COMPLETED"


def build_log_document(
    employee_id: str,
    profile_id: str | None,
    action: LogAction,
    uploaded_count: int = 0,
    unique_count: int = 0,
    duplicate_count: int = 0,
    sent_count: int = 0,
    run_date: datetime | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "employeeId": employee_id,
        "profileId": profile_id,
        "action": action.value,
        "uploadedCount": uploaded_count,
        "uniqueCount": unique_count,
        "duplicateCount": duplicate_count,
        "sentCount": sent_count,
        "runDate": run_date or now,
        "createdAt": now,
    }
