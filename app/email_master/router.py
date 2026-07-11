from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.dependencies import CurrentUser, get_current_user, resolve_employee_context
from app.core.exceptions import BadRequestException
from app.email_master import service
from app.schemas.common import ApiResponse, PaginationParams
from app.utils.pagination import pagination_params

router = APIRouter(prefix="/email-master", tags=["Email Master"])

_ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")


@router.post("/upload", response_model=ApiResponse)
async def upload_emails(
    file: UploadFile = File(...),
    insertDuplicates: bool = Query(default=False),
    maxLimit: int | None = Query(default=None, ge=1, le=10000, description="Maximum emails to upload from file"),
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Upload email CSV/Excel file. Admins can specify employeeId."""
    if not any(file.filename.lower().endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise BadRequestException("Only .csv, .xlsx, and .xls files are supported")

    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    file_bytes = await file.read()
    result = await service.upload_file(
        employee_id, file_bytes, file.filename, insertDuplicates, maxLimit
    )
    return ApiResponse(message="File processed", data=result)


@router.get("/dropdown-options", response_model=ApiResponse)
async def get_dropdown_options(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get dropdown filter options. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    result = await service.get_dropdown_options(employee_id)
    return ApiResponse(message="Dropdown options fetched", data=result)


@router.post("/count-filtered", response_model=ApiResponse)
async def count_filtered_emails(
    filters: dict,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Count emails matching filters. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    result = await service.count_filtered_emails(employee_id, filters)
    return ApiResponse(message="Filtered email count", data=result)


@router.get("/{email_id}", response_model=ApiResponse)
async def get_email(
    email_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get email record. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    record = await service.get_email(email_id)
    # Validate ownership
    if not is_admin and record.get("employeeId") != employee_id:
        raise BadRequestException("Access denied to this email record")
    return ApiResponse(message="Email record fetched", data=record)


@router.get("", response_model=ApiResponse)
async def list_emails(
    employeeId: str | None = Query(default=None),
    country: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    company: str | None = Query(default=None),
    search: str | None = Query(default=None),
    includeDuplicates: bool = Query(default=True),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List emails. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)

    result = await service.list_emails(
        employee_id if employee_id else None,
        params,
        country=country,
        domain=domain,
        industry=industry,
        company=company,
        include_duplicates=includeDuplicates,
        search=search,
    )
    return ApiResponse(message="Emails fetched", data=result)
