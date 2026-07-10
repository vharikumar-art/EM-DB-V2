from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.dependencies import CurrentUser, get_current_user
from app.emails import service
from app.employees.service import get_employee_by_user_id
from app.schemas.common import ApiResponse, PaginationParams
from app.utils.pagination import pagination_params

router = APIRouter(prefix="/emails", tags=["Emails"])


@router.post("/upload", response_model=ApiResponse)
async def upload_emails(
    file: UploadFile = File(...),
    insertDuplicates: bool = Query(default=False),
    current_user: CurrentUser = Depends(get_current_user),
):
    if not (file.filename.lower().endswith(".csv") or file.filename.lower().endswith(".xlsx") or file.filename.lower().endswith(".xls")):
        from app.core.exceptions import BadRequestException

        raise BadRequestException("Only .csv, .xlsx, and .xls files are supported")

    employee = await get_employee_by_user_id(current_user.user_id)
    file_bytes = await file.read()
    result = await service.upload_file(employee["id"], file_bytes, file.filename, insertDuplicates)
    return ApiResponse(message="File processed", data=result)


@router.get("/dropdown-options", response_model=ApiResponse)
async def get_dropdown_options(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        if not employeeId:
            from app.core.exceptions import BadRequestException
            raise BadRequestException("employeeId is required for admins")
        target_employee_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_employee_id = employee["id"]

    result = await service.get_dropdown_options(target_employee_id)
    return ApiResponse(message="Dropdown options fetched", data=result)


@router.get("", response_model=ApiResponse)
async def list_emails(
    employeeId: str | None = Query(default=None),
    country: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    includeDuplicates: bool = Query(default=True),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        target_employee_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_employee_id = employee["id"]

    result = await service.list_emails(
        target_employee_id, params, country=country, domain=domain, include_duplicates=includeDuplicates
    )
    return ApiResponse(message="Emails fetched", data=result)
