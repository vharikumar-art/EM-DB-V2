from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, get_current_user
from app.employees.service import get_employee_by_user_id
from app.logs import service
from app.schemas.common import ApiResponse, PaginationParams
from app.utils.pagination import pagination_params

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("", response_model=ApiResponse)
async def list_logs(
    employeeId: str | None = Query(default=None),
    action: str | None = Query(default=None),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        target_employee_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_employee_id = employee["id"]

    result = await service.list_logs(target_employee_id, params, action_filter=action)
    return ApiResponse(message="Logs fetched", data=result)
