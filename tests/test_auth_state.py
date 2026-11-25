import asyncio
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import service as auth_service
from app.core import dependencies
from app.core.auth_state import UserAuthState, load_active_user_auth_state
from app.core.exceptions import UnauthorizedException


class UsersCollection:
    def __init__(self, user):
        self.user = user
        self.query = None

    async def find_one(self, query, projection):
        self.query = (query, projection)
        return self.user


@pytest.mark.parametrize(
    "user",
    [
        None,
        {"status": "inactive", "role": "admin"},
    ],
)
def test_inactive_or_missing_user_cannot_load_auth_state(monkeypatch, user):
    collection = UsersCollection(user)
    monkeypatch.setattr(
        "app.core.auth_state.get_collection", lambda _name: collection
    )

    with pytest.raises(UnauthorizedException):
        asyncio.run(load_active_user_auth_state(str(ObjectId())))


def test_access_token_uses_current_database_role_and_access_level(monkeypatch):
    async def current_state(_user_id):
        return UserAuthState(role="admin", access_level="partial")

    monkeypatch.setattr(dependencies, "load_active_user_auth_state", current_state)
    monkeypatch.setattr(
        dependencies,
        "decode_token",
        lambda _token: {
            "type": "access",
            "sub": "507f1f77bcf86cd799439011",
            "role": "super_admin",
            "accessLevel": "full",
        },
    )

    current_user = asyncio.run(
        dependencies.get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="access-token")
        )
    )

    assert current_user.role == "admin"
    assert current_user.access_level == "partial"


def test_refresh_uses_current_role_instead_of_token_claims(monkeypatch):
    user_id = "507f1f77bcf86cd799439011"
    issued_tokens = []

    class RevokedTokens:
        async def find_one(self, _query):
            return None

    async def current_state(_user_id):
        return UserAuthState(role="admin", access_level="partial")

    def create_token(*args):
        issued_tokens.append(args)
        return f"token-{len(issued_tokens)}"

    monkeypatch.setattr(
        auth_service, "get_collection", lambda _name: RevokedTokens()
    )
    monkeypatch.setattr(
        auth_service,
        "decode_token",
        lambda _token: {
            "type": "refresh",
            "sub": user_id,
            "role": "super_admin",
            "accessLevel": "full",
            "employee_id": "stale-employee-id",
        },
    )
    monkeypatch.setattr(auth_service, "load_active_user_auth_state", current_state)
    monkeypatch.setattr(auth_service, "create_access_token", create_token)
    monkeypatch.setattr(auth_service, "create_refresh_token", create_token)

    tokens = asyncio.run(auth_service.refresh_access_token("old-refresh-token"))

    assert tokens.role == "admin"
    assert tokens.employeeId is None
    assert all(args[1] == "admin" and args[3] == "partial" for args in issued_tokens)
