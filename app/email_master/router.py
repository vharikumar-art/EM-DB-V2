from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import BadRequestException
from app.email_master import service
from app.employees.service import get_employee_by_user_id
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
    if not any(file.filename.lower().endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise BadRequestException("Only .csv, .xlsx, and .xls files are supported")

    employee = await get_employee_by_user_id(current_user.user_id)
    file_bytes = await file.read()
    result = await service.upload_file(
        employee["id"], file_bytes, file.filename, insertDuplicates, maxLimit
    )
    return ApiResponse(message="File processed", data=result)


@router.get("/dropdown-options", response_model=ApiResponse)
async def get_dropdown_options(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        if not employeeId:
            raise BadRequestException("employeeId is required for admins")
        target_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_id = employee["id"]

    result = await service.get_dropdown_options(target_id)
    return ApiResponse(message="Dropdown options fetched", data=result)


@router.get("/{email_id}", response_model=ApiResponse)
async def get_email(
    email_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    record = await service.get_email(email_id)
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
    if current_user.role == "admin":
        target_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_id = employee["id"]

    result = await service.list_emails(
        target_id,
        params,
        country=country,
        domain=domain,
        industry=industry,
        company=company,
        include_duplicates=includeDuplicates,
        search=search,
    )
    return ApiResponse(message="Emails fetched", data=result)
