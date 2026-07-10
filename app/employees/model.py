from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EmployeeStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def build_employee_document(
    user_id: str,
    branch: str | None = None,
    employee_code: str | None = None,
    department: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc: dict[str, Any] = {
        "userId": user_id,
        "branch": branch,
        "department": department,
        "status": EmployeeStatus.ACTIVE.value,
        "createdAt": now,
        "updatedAt": now,
    }
    if employee_code is not None:
        doc["employeeCode"] = employee_code
    return doc


