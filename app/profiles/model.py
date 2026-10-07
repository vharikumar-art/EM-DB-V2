from datetime import datetime, timezone
from typing import Any

MAX_PROFILES_PER_EMPLOYEE = 7


def build_profile_document(
    employee_id: str,
    profile_name: str,
    gmail_account: str,
    signature: str,
    filters: dict[str, Any],
    filter_limit: int,
    sending_options: dict[str, Any],
    prompt_settings: dict[str, Any],
    templates: list[dict[str, str]],
    attachments: list[dict[str, Any]] | None = None,
    employee_name: str | None = None,
    assigned_admin: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    
    return {
        "employeeId": employee_id,
        "profileName": profile_name,
        "gmailAccount": gmail_account,
        "templates": templates,
        "attachments": attachments or [],
        "signature": signature,
        "isActive": True,
        "filters": filters,
        "filterLimit": filter_limit,
        "sendingOptions": sending_options,
        "promptSettings": prompt_settings,
        "employeeName": employee_name or "",
        "assignedAdmin": assigned_admin or "",
        "createdAt": now,
        "updatedAt": now,
    }
