from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.dependencies import CurrentUser, get_current_user, require_admin
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
    current_user: CurrentUser = Depends(get_current_user),
):
    """Upload email CSV/Excel file to global pool. Tracks who uploaded."""
    if not any(file.filename.lower().endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise BadRequestException("Only .csv, .xlsx, and .xls files are supported")

    file_bytes = await file.read()
    
    # Get employee name from database
    from app.employees.service import get_employee_by_user_id
    try:
        employee = await get_employee_by_user_id(current_user.user_id)
        uploaded_by_name = employee.get("name") or current_user.user_id
    except:
        # Fallback to user_id if employee not found
        uploaded_by_name = current_user.user_id
    
    result = await service.upload_file(
        uploaded_by_id=current_user.user_id,
        uploaded_by_name=uploaded_by_name,
        file_bytes=file_bytes,
        filename=file.filename,
        insert_duplicates=insertDuplicates,
        max_limit=maxLimit,
    )
    return ApiResponse(message="File processed", data=result)


@router.get("/dropdown-options", response_model=ApiResponse)
async def get_dropdown_options(
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get dropdown filter options from GLOBAL pool."""
    options = await service.get_dropdown_options()
    return ApiResponse(message="Dropdown options fetched", data=options)


@router.get("/stats/uploaders", response_model=ApiResponse)
async def get_uploader_stats(
    current_user: CurrentUser = Depends(require_admin),
):
    """ADMIN ONLY: Get upload contribution statistics."""
    stats = await service.get_uploader_stats()
    return ApiResponse(message="Uploader statistics", data=stats)


@router.post("/count-filtered", response_model=ApiResponse)
async def count_filtered_emails(
    filters: dict,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Count emails matching filters from GLOBAL pool."""
    result = await service.count_filtered_emails(filters)
    return ApiResponse(message="Filtered email count", data=result)


@router.get("/{email_id}", response_model=ApiResponse)
async def get_email(
    email_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get email record from GLOBAL pool."""
    record = await service.get_email(email_id)
    return ApiResponse(message="Email record fetched", data=record)


@router.delete("/{email_id}", response_model=ApiResponse)
async def delete_email(
    email_id: str,
    current_user: CurrentUser = Depends(require_admin),
):
    """ADMIN ONLY: Delete email from GLOBAL pool."""
    await service.delete_email(email_id)
    return ApiResponse(message="Email deleted")


@router.get("", response_model=ApiResponse)
async def list_emails(
    country: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    company: str | None = Query(default=None),
    uploadedBy: str | None = Query(default=None),
    search: str | None = Query(default=None),
    includeDuplicates: bool = Query(default=True),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List emails from GLOBAL pool with filters."""
    result = await service.list_emails(
        params,
        country=country,
        domain=domain,
        industry=industry,
        company=company,
        uploaded_by=uploadedBy,
        include_duplicates=includeDuplicates,
        search=search,
    )
    
    # Get dropdown options to include in response
    options = await service.get_dropdown_options()
    
    return ApiResponse(
        message="Emails fetched",
        data=result,
        options=options,
    )
