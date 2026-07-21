from datetime import datetime, timezone
from enum import Enum
from typing import Any


class UserRole(str, Enum):
    ADMIN = "admin"
    EMPLOYEE = "employee"


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def build_user_document(
    name: str,
    email: str,
    hashed_password: str,
    role: UserRole,
    encrypted_password: str,
    branch: str | None = None,
    status: UserStatus = UserStatus.ACTIVE,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "name": name,
        "email": email,
        "password": hashed_password,
        "passwordEncrypted": encrypted_password,
        "role": role.value,
        "status": status.value,
        "branch": branch or "Default",  # All users get a branch (admin or employee)
        "createdAt": now,
        "updatedAt": now,
    }
