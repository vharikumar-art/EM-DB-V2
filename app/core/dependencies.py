from fastapi import Depends, Header

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise UnauthorizedException("Missing bearer token")
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise UnauthorizedException(str(exc)) from exc

    if payload.get("type") != "access":
        raise UnauthorizedException("Provide an access token, not a refresh token")

    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or not role:
        raise UnauthorizedException("Malformed token payload")

    return CurrentUser(user_id=user_id, role=role)


def require_roles(*allowed_roles: str):
    async def _checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise ForbiddenException(
                f"Role '{current_user.role}' is not permitted. Requires one of: {allowed_roles}"
            )
        return current_user

    return _checker


require_admin = require_roles("admin")
require_any_role = require_roles("admin", "employee")


async def verify_n8n_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Guards webhooks called by n8n using a shared secret instead of a user JWT."""
    if not x_api_key or x_api_key != settings.N8N_API_KEY:
        raise UnauthorizedException("Invalid or missing n8n API key")
