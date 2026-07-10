from datetime import datetime, timezone
from typing import Any


def build_template_document(
    employee_id: str,
    name: str,
    subject: str,
    body: str,
    signature: str,
    tags: list[str],
    is_global: bool,
) -> dict[str, Any]:
    """
    A reusable email template.

    is_global=True  → created by admin, visible to all employees (read-only for employees).
    is_global=False → owned by the employee, private to them.

    Supports placeholders: [name], [company], [industry], [designation], [country]
    These are replaced at send time by the LangChain personalizer.
    """
    now = datetime.now(timezone.utc)
    return {
        "employeeId": employee_id,   # admin's user_id when is_global=True
        "name": name,
        "subject": subject,
        "body": body,
        "signature": signature,
        "tags": tags,
        "isGlobal": is_global,
        "usageCount": 0,             # incremented each time a campaign uses this template
        "createdAt": now,
        "updatedAt": now,
    }
