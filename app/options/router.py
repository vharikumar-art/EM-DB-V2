"""
Dropdown Options Endpoint

Provides lists of entities (employees, profiles, campaigns) for UI dropdowns.
Used by admin to select which employee/profile/campaign to act on.
"""

from fastapi import APIRouter, Depends, Query

from app.campaigns.service import list_campaigns
from app.core.dependencies import CurrentUser, get_current_user, require_admin
from app.employees.service import get_employee_by_user_id
from app.profiles.service import list_profiles
from app.schemas.common import ApiResponse
from app.users.service import list_users
from app.database.mongodb import get_collection
from app.utils.pagination import PaginationParams
from app.utils.response import serialize_doc

router = APIRouter(prefix="/options", tags=["Options"])


@router.get("/employees", response_model=ApiResponse)
async def get_employees_options(
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Get list of employees (users with role=employee) for dropdown (admin only).
    
    Returns: List of {id, name, email, branch} where id is the EMPLOYEE ID
    """
    users_col = get_collection("users")
    employees_col = get_collection("employees")
    from bson import ObjectId

    # Get all users with role 'employee'
    users_docs = await users_col.find({"role": "employee"}).to_list(None)

    options = []
    for user_doc in users_docs:
        user_id = str(user_doc["_id"])
        # Find their employee record (this is the ID stored in profiles/campaigns)
        emp_doc = await employees_col.find_one({"userId": user_id})
        if not emp_doc:
            # Auto-create employee record so the ID system stays consistent
            from app.employees.model import build_employee_document
            new_emp = build_employee_document(user_id=user_id, branch=user_doc.get("branch"))
            result = await employees_col.insert_one(new_emp)
            emp_doc = await employees_col.find_one({"_id": result.inserted_id})

        options.append({
            "id": str(emp_doc["_id"]),   # employee._id — matches profileId, campaignId, etc.
            "userId": user_id,
            "name": user_doc.get("name", "Unknown"),
            "email": user_doc.get("email", ""),
            "branch": user_doc.get("branch", emp_doc.get("branch", "")),
        })

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
