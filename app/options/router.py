"""
Dropdown Options Endpoint

Provides lists of entities (employees, profiles, campaigns) for UI dropdowns.
Used by admin to select which employee/profile/campaign to act on.
"""

from fastapi import APIRouter, Depends, Query

from app.campaigns.service import list_campaigns
from app.core.dependencies import CurrentUser, get_current_user, require_admin
from app.profiles.service import list_profiles
from app.schemas.common import ApiResponse
from app.users.service import list_users
from app.utils.pagination import PaginationParams
from app.utils.response import serialize_doc

router = APIRouter(prefix="/options", tags=["Options"])


@router.get("/employees", response_model=ApiResponse)
async def get_employees_options(
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Get list of employees (users with role=employee) for dropdown (admin only).
    
    Returns: List of {id, name, email, branch}
    """
    all_users = await list_users()
    # Filter only employees
    employees = [u for u in all_users if u.get("role") == "employee"]
    options = [
        {
            "id": emp["id"],
            "name": emp.get("name", ""),
            "email": emp.get("email", ""),
            "branch": emp.get("branch", ""),
        }
        for emp in employees
    ]
    return ApiResponse(message="Employees fetched", data=options)


@router.get("/profiles", response_model=ApiResponse)
async def get_profiles_options(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get list of profiles for dropdown.
    
    - Employee: Returns only their own profiles
    - Admin: Can specify employeeId to get another employee's profiles
    
    Returns: List of {id, profileName, gmailAccount}
    """
    # Resolve employee context
    if current_user.role == "admin":
        if not employeeId:
            return ApiResponse(message="Admins must specify employeeId", data=[])
        target_employee_id = employeeId
    else:
        # Employee views their own profiles
        employee = await get_employee_by_user_id(current_user.user_id)
        target_employee_id = employee["id"]

    profiles = await list_profiles(target_employee_id)
    options = [
        {
            "id": prof["id"],
            "profileName": prof.get("profileName", ""),
            "gmailAccount": prof.get("gmailAccount", ""),
        }
        for prof in profiles
    ]
    return ApiResponse(message="Profiles fetched", data=options)


@router.get("/campaigns", response_model=ApiResponse)
async def get_campaigns_options(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get list of campaigns for dropdown.
    
    - Employee: Returns only their own campaigns
    - Admin: Can specify employeeId to get another employee's campaigns
    
    Returns: List of {id, profileName, status}
    """
    # Resolve employee context
    if current_user.role == "admin":
        if not employeeId:
            return ApiResponse(message="Admins must specify employeeId", data=[])
        target_employee_id = employeeId
    else:
        # Employee views their own campaigns
        employee = await get_employee_by_user_id(current_user.user_id)
        target_employee_id = employee["id"]

    # Get campaigns with minimal pagination (just get all for dropdown)
    params = PaginationParams(pageIndex=0, pageSize=1000)
    result = await list_campaigns(
        employee_id=target_employee_id,
        params=params,
    )

    campaigns = result.get("data", [])
    options = [
        {
            "id": camp["id"],
            "profileName": camp.get("profileName", ""),
            "status": camp.get("status", ""),
        }
        for camp in campaigns
    ]
    return ApiResponse(message="Campaigns fetched", data=options)
