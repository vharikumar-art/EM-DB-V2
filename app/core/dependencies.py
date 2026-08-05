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


require_super_admin = require_roles("super_admin")
require_admin = require_roles("super_admin", "admin")
require_any_role = require_roles("super_admin", "admin", "employee")



async def resolve_employee_context(
    current_user: CurrentUser, 
    employee_id_param: str | None = None
) -> tuple[str | list[str] | None, bool]:
    """
    Centralized employee context resolution for all routers.
    Returns: (employee_id(s), is_admin)
    """
    from app.employees.service import get_employee_by_user_id
    from app.database.mongodb import get_collection
    from app.utils.response import to_object_id
    
    if current_user.role == "super_admin":
        return employee_id_param, True
    
    # Non-super-admin: get their actual employee_id from employees collection
    try:
        employee = await get_employee_by_user_id(current_user.user_id)
        employee_id = str(employee.get("id", current_user.user_id))
    except Exception:
        employee_id = current_user.user_id
        
    if current_user.role == "admin":
        employees_col = get_collection("employees")
        if employee_id_param:
            if employee_id_param == employee_id:
                return employee_id, True
            try:
                target_emp = await employees_col.find_one({"_id": to_object_id(employee_id_param)})
                if target_emp and str(target_emp.get("assignedToAdmin")) == employee_id:
                    return employee_id_param, True
            except Exception:
                pass
            raise ForbiddenException("You do not have access to this employee's data")
        else:
            # Return list of their own ID + subordinates
            subordinates = await employees_col.find({"assignedToAdmin": employee_id}).to_list(None)
            allowed_ids = [employee_id] + [str(sub["_id"]) for sub in subordinates]
            return allowed_ids, True
            
    return employee_id, False


async def validate_data_ownership(
    resource: dict,
    employee_id: str | list[str] | None,
    is_admin: bool,
    resource_type: str = "resource"
) -> None:
    """
    Centralized ownership validation for all data access.
    """
    if resource is None:
        raise NotFoundException(f"{resource_type.capitalize()} not found")
    
    if is_admin:
        return
        
    resource_owner = resource.get("employeeId")
    
    if isinstance(employee_id, list):
        if resource_owner in employee_id:
            return
    elif resource_owner == employee_id:
        return
        
    raise ForbiddenException(
        f"You do not have access to this {resource_type}"
    )
