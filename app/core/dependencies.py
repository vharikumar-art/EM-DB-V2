from fastapi import Depends, Header

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.exceptions import ForbiddenException, UnauthorizedException, NotFoundException
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


async def resolve_employee_context(
    current_user: CurrentUser, 
    employee_id_param: str | None = None
) -> tuple[str, bool]:
    """
    Centralized employee context resolution for all routers.
    
    Returns tuple: (employee_id, is_admin)
    
    For admins:
        - If employee_id_param provided: acts as that user/employee
        - If employee_id_param None: returns ("", True) for all-employees context
        
    For employees:
        - Always uses their own user_id
        - Ignores employee_id_param (cannot act as others)
    
    Args:
        current_user: Authenticated user from token (has user_id field)
        employee_id_param: Optional employeeId/userId from query/path parameter
        
    Returns:
        (employee_id, is_admin): employee context and admin flag
    """
    if current_user.role == "admin":
        # Admin can act as specific employee/user or all employees (empty string means all)
        return employee_id_param or "", True
    
    # Non-admin: must be employee, use their own user_id
    return current_user.user_id, False


async def validate_data_ownership(
    resource: dict,
    employee_id: str,
    is_admin: bool,
    resource_type: str = "resource"
) -> None:
    """
    Centralized ownership validation for all data access.
    
    Enforces: Non-admins can only access their own data.
    
    Args:
        resource: The data object being accessed (must have 'employeeId' field)
        employee_id: Current user's employee ID
        is_admin: Whether current user is admin
        resource_type: Friendly name for error messages (e.g., "profile", "campaign")
        
    Raises:
        NotFoundException: If resource is None
        ForbiddenException: If non-admin trying to access other's data
    """
    if resource is None:
        raise NotFoundException(f"{resource_type.capitalize()} not found")
    
    resource_owner = resource.get("employeeId")
    if not is_admin and resource_owner != employee_id:
        raise ForbiddenException(
            f"You do not have access to this {resource_type}"
        )
