from datetime import datetime, timezone
from enum import Enum
from typing import Any


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    EMPLOYEE = "employee"


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AdminAccessLevel(str, Enum):
    PARTIAL = "partial"
    FULL = "full"


def build_user_document(
    name: str,
    email: str,
    phone_number: str | None,
    hashed_password: str,
    role: UserRole,
    encrypted_password: str,
    access_level: str = AdminAccessLevel.FULL.value,
    branch: str | None = None,
    status: UserStatus = UserStatus.ACTIVE,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "name": name,
        "email": email,
        "phoneNumber": phone_number,
        "accessLevel": access_level,
        "password": hashed_password,
        "passwordEncrypted": encrypted_password,
        "role": role.value,
        "status": status.value,
        "branch": branch or None,
        "createdAt": now,
        "updatedAt": now,
    }
