import asyncio

import pytest

from app.core.dependencies import CurrentUser, require_write_access
from app.core.exceptions import ForbiddenException


def _check_write_access(role: str, access_level: str = "full"):
    return asyncio.run(
        require_write_access(CurrentUser("user-id", role, access_level))
    )


def test_partial_admin_is_read_only():
    with pytest.raises(ForbiddenException, match="read-only"):
        _check_write_access("admin", "partial")


def test_full_admin_can_write():
    user = _check_write_access("admin", "full")
    assert user.access_level == "full"


def test_super_admin_can_write_regardless_of_access_level():
    user = _check_write_access("super_admin", "partial")
    assert user.role == "super_admin"


def test_employee_permission_is_unchanged():
    user = _check_write_access("employee")
    assert user.role == "employee"