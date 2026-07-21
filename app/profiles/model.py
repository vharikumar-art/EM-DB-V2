from datetime import datetime, timezone
from typing import Any

MAX_PROFILES_PER_EMPLOYEE = 5


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
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    
    return {
        "employeeId": employee_id,
        "profileName": profile_name,
        "gmailAccount": gmail_account,
        "templates": templates,
        "signature": signature,
        "isActive": True,
        "filters": filters,
        "filterLimit": filter_limit,
        "sendingOptions": sending_options,
        "promptSettings": prompt_settings,
        "createdAt": now,
        "updatedAt": now,
    }
