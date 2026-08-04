from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUser, get_current_user, resolve_employee_context
from app.schemas.common import ApiResponse, PaginationParams
from app.templates import service
from app.templates.schema import TemplateCreate, TemplatePreviewRequest, TemplateUpdate
from app.utils.pagination import pagination_params

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await resolve_employee_context(current_user)
    template = await service.create_template(employee_id, is_admin, payload)
    return ApiResponse(message="Template created", data=template)


@router.get("", response_model=ApiResponse)
async def list_templates(
    tag: str | None = Query(default=None),
    search: str | None = Query(default=None),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await resolve_employee_context(current_user)
    result = await service.list_templates(employee_id, is_admin, params, tag=tag, search=search)
    return ApiResponse(message="Templates fetched", data=result)


@router.get("/{template_id}", response_model=ApiResponse)
async def get_template(
    template_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await resolve_employee_context(current_user)
    template = await service.get_template(template_id, employee_id, is_admin)
    return ApiResponse(message="Template fetched", data=template)


@router.patch("/{template_id}", response_model=ApiResponse)
async def update_template(
    template_id: str,
    payload: TemplateUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await resolve_employee_context(current_user)
    template = await service.update_template(template_id, employee_id, is_admin, payload)
    return ApiResponse(message="Template updated", data=template)


@router.delete("/{template_id}", response_model=ApiResponse)
async def delete_template(
    template_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await resolve_employee_context(current_user)
    await service.delete_template(template_id, employee_id, is_admin)
    return ApiResponse(message="Template deleted")


@router.post("/preview", response_model=ApiResponse)
async def preview_template(
    payload: TemplatePreviewRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Render a template with a sample lead — no email is sent."""
    employee_id, is_admin = await resolve_employee_context(current_user)
    result = await service.preview_template(
        payload.templateId, employee_id, is_admin, payload.sampleLead
    )
    return ApiResponse(message="Preview generated", data=result)
