from datetime import datetime, timezone
from typing import Any

MAX_PROFILES_PER_EMPLOYEE = 5


def build_profile_document(
    employee_id: str,
    profile_name: str,
    gmail_account: str,
    subject: str,
    body: str,
    signature: str,
    filters: dict[str, Any],
    sending_options: dict[str, Any],
    prompt_settings: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "employeeId": employee_id,
        "profileName": profile_name,
        "gmailAccount": gmail_account,
        "subject": subject,
        "body": body,
        "signature": signature,
        "isActive": True,
        "filters": filters,
        "sendingOptions": sending_options,
        "promptSettings": prompt_settings,
        "createdAt": now,
        "updatedAt": now,
    }
