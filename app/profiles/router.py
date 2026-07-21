from fastapi import APIRouter, Depends, Query, UploadFile, File

from app.core.dependencies import CurrentUser, get_current_user, resolve_employee_context
from app.core.exceptions import BadRequestException
from app.profiles import service
from app.profiles.schema import ProfileCreate, ProfileUpdate
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/profiles", tags=["Profiles"])


@router.post("", response_model=ApiResponse)
async def create_profile(
    payload: ProfileCreate,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new profile. Admins must specify employeeId."""
    if current_user.role == "admin" and not employeeId:
        raise BadRequestException("Admins must specify employeeId")
    
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.create_profile(employee_id, payload)
    return ApiResponse(message="Profile created", data=profile)


@router.get("", response_model=ApiResponse)
async def list_profiles(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List profiles. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profiles = await service.list_profiles(employee_id if employee_id else None)
    return ApiResponse(message="Profiles fetched", data=profiles)


@router.get("/{profile_id}", response_model=ApiResponse)
async def get_profile(
    profile_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get profile details. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.get_profile(profile_id, employee_id, is_admin)
    return ApiResponse(message="Profile fetched", data=profile)


@router.patch("/{profile_id}", response_model=ApiResponse)
async def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update profile. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.update_profile(profile_id, employee_id, is_admin, payload)
    return ApiResponse(message="Profile updated", data=profile)


@router.post("/{profile_id}/activate", response_model=ApiResponse)
async def activate_profile(
    profile_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Activate profile. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.set_active_status(profile_id, employee_id, is_admin, True)
    return ApiResponse(message="Profile activated", data=profile)


@router.post("/{profile_id}/deactivate", response_model=ApiResponse)
async def deactivate_profile(
    profile_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Deactivate profile. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.set_active_status(profile_id, employee_id, is_admin, False)
    return ApiResponse(message="Profile deactivated", data=profile)


@router.delete("/{profile_id}", response_model=ApiResponse)
async def delete_profile(
    profile_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete profile. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    await service.delete_profile(profile_id, employee_id, is_admin)
    return ApiResponse(message="Profile deleted")


@router.post("/{profile_id}/templates", response_model=ApiResponse)
async def add_template(
    profile_id: str,
    payload: dict,  # TemplateAdd
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a new template to a profile"""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.add_template(profile_id, employee_id, is_admin, payload)
    return ApiResponse(message="Template added", data=profile)


@router.patch("/{profile_id}/templates/{template_id}", response_model=ApiResponse)
async def update_template(
    profile_id: str,
    template_id: str,
    payload: dict,  # TemplateUpdate
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a template in a profile"""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.update_template(profile_id, employee_id, is_admin, template_id, payload)
    return ApiResponse(message="Template updated", data=profile)


@router.delete("/{profile_id}/templates/{template_id}", response_model=ApiResponse)
async def delete_template(
    profile_id: str,
    template_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete a template from a profile"""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    profile = await service.delete_template(profile_id, employee_id, is_admin, template_id)
    return ApiResponse(message="Template deleted", data=profile)


@router.post("/{profile_id}/templates/{template_id}/upload-attachment", response_model=ApiResponse)
async def upload_attachment(
    profile_id: str,
    template_id: str,
    file: UploadFile = File(...),
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Upload an attachment file for a template"""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    result = await service.upload_attachment(profile_id, template_id, file, employee_id, is_admin)
    return ApiResponse(message="Attachment uploaded", data=result)


@router.delete("/{profile_id}/templates/{template_id}/attachments/{attachment_id}", response_model=ApiResponse)
async def delete_attachment(
    profile_id: str,
    template_id: str,
    attachment_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete an attachment from a template"""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    result = await service.delete_attachment(profile_id, template_id, attachment_id, employee_id, is_admin)
    return ApiResponse(message="Attachment deleted", data=result)

