from datetime import date

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, get_current_user, require_admin
from app.dashboard import service
from app.dashboard.schema import DashboardQuery, DateRangePreset
from app.employees.service import get_employee_by_user_id
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _dashboard_query(
    preset: DateRangePreset = Query(default=DateRangePreset.LAST_7_DAYS),
    startDate: date | None = Query(default=None),
    endDate: date | None = Query(default=None),
) -> DashboardQuery:
    return DashboardQuery(preset=preset, startDate=startDate, endDate=endDate)


@router.get("/employee", response_model=ApiResponse)
async def employee_dashboard(
    employeeId: str | None = Query(default=None),
    query: DashboardQuery = Depends(_dashboard_query),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        if not employeeId:
            from app.core.exceptions import BadRequestException
            raise BadRequestException("Admins must provide employeeId to view an employee dashboard, or use /dashboard/admin")
        target_employee_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_employee_id = employee["id"]
        
    data = await service.get_employee_dashboard(target_employee_id, query)
    return ApiResponse(message="Employee dashboard fetched", data=data)


@router.get("/admin", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def admin_dashboard(query: DashboardQuery = Depends(_dashboard_query)):
    data = await service.get_admin_dashboard(query)
    return ApiResponse(message="Admin dashboard fetched", data=data)
