from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, get_current_user
from app.employees.service import get_employee_by_user_id
from app.profiles import service
from app.profiles.schema import ProfileCreate, ProfileUpdate
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/profiles", tags=["Profiles"])


async def _resolve_employee_id(current_user: CurrentUser, employee_id_query: str | None) -> str:
    """Admins may act on behalf of a given employeeId; employees are scoped to themselves."""
    if current_user.role == "admin":
        if not employee_id_query:
            raise ValueError("employeeId query parameter is required for admin requests")
        return employee_id_query
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"]


@router.post("", response_model=ApiResponse)
async def create_profile(
    payload: ProfileCreate,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id = await _resolve_employee_id(current_user, employeeId)
    profile = await service.create_profile(employee_id, payload)
    return ApiResponse(message="Profile created", data=profile)


@router.get("", response_model=ApiResponse)
async def list_profiles(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        profiles = await service.list_profiles(employeeId)
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        profiles = await service.list_profiles(employee["id"])
    return ApiResponse(message="Profiles fetched", data=profiles)


@router.get("/{profile_id}", response_model=ApiResponse)
async def get_profile(profile_id: str, current_user: CurrentUser = Depends(get_current_user)):
    employee_id = (
        (await get_employee_by_user_id(current_user.user_id))["id"]
        if current_user.role != "admin"
        else ""
    )
    profile = await service.get_profile(profile_id, employee_id, current_user.role == "admin")
    return ApiResponse(message="Profile fetched", data=profile)


@router.patch("/{profile_id}", response_model=ApiResponse)
async def update_profile(
    profile_id: str, payload: ProfileUpdate, current_user: CurrentUser = Depends(get_current_user)
):
    employee_id = (
        (await get_employee_by_user_id(current_user.user_id))["id"]
        if current_user.role != "admin"
        else ""
    )
    profile = await service.update_profile(profile_id, employee_id, current_user.role == "admin", payload)
    return ApiResponse(message="Profile updated", data=profile)


@router.post("/{profile_id}/activate", response_model=ApiResponse)
async def activate_profile(profile_id: str, current_user: CurrentUser = Depends(get_current_user)):
    employee_id = (
        (await get_employee_by_user_id(current_user.user_id))["id"]
        if current_user.role != "admin"
        else ""
    )
    profile = await service.set_active_status(profile_id, employee_id, current_user.role == "admin", True)
    return ApiResponse(message="Profile activated", data=profile)


@router.post("/{profile_id}/deactivate", response_model=ApiResponse)
async def deactivate_profile(profile_id: str, current_user: CurrentUser = Depends(get_current_user)):
    employee_id = (
        (await get_employee_by_user_id(current_user.user_id))["id"]
        if current_user.role != "admin"
        else ""
    )
    profile = await service.set_active_status(profile_id, employee_id, current_user.role == "admin", False)
    return ApiResponse(message="Profile deactivated", data=profile)


@router.delete("/{profile_id}", response_model=ApiResponse)
async def delete_profile(profile_id: str, current_user: CurrentUser = Depends(get_current_user)):
    employee_id = (
        (await get_employee_by_user_id(current_user.user_id))["id"]
        if current_user.role != "admin"
        else ""
    )
    await service.delete_profile(profile_id, employee_id, current_user.role == "admin")
    return ApiResponse(message="Profile deleted")
