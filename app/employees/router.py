from fastapi import APIRouter, Depends, status

from app.core.dependencies import CurrentUser, get_current_user, require_admin
from app.employees import service
from app.employees.schema import EmployeeCreate, EmployeeUpdate
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/employees", tags=["Employees"])


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_employee(payload: EmployeeCreate, current_user: CurrentUser = Depends(get_current_user)):
    employee = await service.create_employee(payload)
    
    from app.notifications.service import create_notification
    from app.notifications.schema import NotificationType
    
    await create_notification(
        employee_id=current_user.user_id,
        message=f"New employee '{payload.name}' was created successfully.",
        type=NotificationType.SUCCESS,
    )
    
    return ApiResponse(message="Employee created successfully", data=employee)


@router.get("", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def list_employees():
    employees = await service.list_employees()
    return ApiResponse(message="Employees fetched", data=employees)


@router.get("/me", response_model=ApiResponse)
async def get_my_employee_record(current_user: CurrentUser = Depends(get_current_user)):
    employee = await service.get_employee_by_user_id(current_user.user_id)
    return ApiResponse(message="Employee record fetched", data=employee)


@router.get("/{employee_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def get_employee(employee_id: str):
    employee = await service.get_employee(employee_id)
    return ApiResponse(message="Employee fetched", data=employee)


@router.patch("/{employee_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def update_employee(employee_id: str, payload: EmployeeUpdate):
    employee = await service.update_employee(employee_id, payload)
    return ApiResponse(message="Employee updated", data=employee)


@router.delete("/{employee_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def delete_employee(employee_id: str):
    await service.delete_employee(employee_id)
    return ApiResponse(message="Employee deleted")
