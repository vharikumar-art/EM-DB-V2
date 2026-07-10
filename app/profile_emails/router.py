from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUser, get_current_user
from app.employees.service import get_employee_by_user_id
from app.profile_emails import service
from app.profile_emails.schema import (
    GenerateListRequest,
    ProfileEmailUpdate,
)
from app.schemas.common import ApiResponse, PaginationParams
from app.utils.pagination import pagination_params

router = APIRouter(prefix="/profile-emails", tags=["Profile Emails"])


async def _resolve_employee(current_user: CurrentUser) -> tuple[str, bool]:
    """Returns (employee_id, is_admin)."""
    is_admin = current_user.role == "admin"
    if is_admin:
        return "", True
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"], False


# ---------------------------------------------------------------------------
# Generate list
# ---------------------------------------------------------------------------

@router.post("/{profile_id}/generate", response_model=ApiResponse)
async def generate_list(
    profile_id: str,
    payload: GenerateListRequest = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Apply profile filters against email_master and populate the working list.
    Existing PENDING rows are replaced; SENT / FAILED rows are preserved.
    """
    employee_id, is_admin = await _resolve_employee(current_user)
    payload = payload or GenerateListRequest()
    result = await service.generate_list(
        profile_id=profile_id,
        employee_id=employee_id,
        is_admin=is_admin,
        override_filters=payload.overrideFilters,
        limit_override=payload.limitOverride,
    )
    return ApiResponse(message="Profile email list generated", data=result)


# ---------------------------------------------------------------------------
# List / stats
# ---------------------------------------------------------------------------

@router.get("/{profile_id}/stats", response_model=ApiResponse)
async def get_stats(
    profile_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    stats = await service.get_stats(profile_id, employee_id, is_admin)
    return ApiResponse(message="Stats fetched", data=stats)


@router.get("/{profile_id}", response_model=ApiResponse)
async def list_profile_emails(
    profile_id: str,
    sendStatus: str | None = Query(default=None),
    search: str | None = Query(default=None),
    country: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    result = await service.list_profile_emails(
        profile_id=profile_id,
        employee_id=employee_id,
        is_admin=is_admin,
        params=params,
        send_status=sendStatus,
        search=search,
        country=country,
        domain=domain,
    )
    return ApiResponse(message="Profile emails fetched", data=result)


# ---------------------------------------------------------------------------
# Single row CRUD
# ---------------------------------------------------------------------------

@router.get("/record/{profile_email_id}", response_model=ApiResponse)
async def get_profile_email(
    profile_email_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    record = await service.get_profile_email(profile_email_id, employee_id, is_admin)
    return ApiResponse(message="Record fetched", data=record)


@router.patch("/record/{profile_email_id}", response_model=ApiResponse)
async def update_profile_email(
    profile_email_id: str,
    payload: ProfileEmailUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    updated = await service.update_profile_email(
        profile_email_id,
        employee_id,
        is_admin,
        payload.model_dump(exclude_unset=True),
    )
    return ApiResponse(message="Record updated", data=updated)


@router.delete(
    "/record/{profile_email_id}",
    response_model=ApiResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_profile_email(
    profile_email_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete a single row. Email Master is never affected."""
    employee_id, is_admin = await _resolve_employee(current_user)
    await service.delete_profile_email(profile_email_id, employee_id, is_admin)
    return ApiResponse(message="Record deleted")


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

@router.post("/{profile_id}/retry-failed", response_model=ApiResponse)
async def retry_failed(
    profile_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Reset all FAILED emails in this profile to PENDING for re-sending."""
    employee_id, is_admin = await _resolve_employee(current_user)
    result = await service.retry_failed(profile_id, employee_id, is_admin)
    return ApiResponse(message="Failed emails reset to pending", data=result)


@router.delete("/{profile_id}/clear", response_model=ApiResponse)
async def clear_profile_list(
    profile_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete the entire working list for this profile. Email Master is never affected."""
    employee_id, is_admin = await _resolve_employee(current_user)
    result = await service.clear_profile_list(profile_id, employee_id, is_admin)
    return ApiResponse(message="Profile list cleared", data=result)


@router.post("/bulk-delete", response_model=ApiResponse)
async def bulk_delete(
    ids: list[str],
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete multiple profile_email rows by ID."""
    employee_id, is_admin = await _resolve_employee(current_user)
    result = await service.bulk_delete(ids, employee_id, is_admin)
    return ApiResponse(message="Records deleted", data=result)
