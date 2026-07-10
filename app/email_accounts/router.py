from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUser, get_current_user
from app.email_accounts import service
from app.email_accounts.schema import EmailAccountCreate, EmailAccountUpdate
from app.employees.service import get_employee_by_user_id
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/email-accounts", tags=["Email Accounts"])


async def _resolve_employee(current_user: CurrentUser) -> tuple[str, bool]:
    is_admin = current_user.role == "admin"
    if is_admin:
        return current_user.user_id, True
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"], False


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: EmailAccountCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a Gmail / SMTP account. The app-password is encrypted at rest immediately."""
    employee_id, is_admin = await _resolve_employee(current_user)
    account = await service.create_account(employee_id, payload)
    return ApiResponse(message="Email account added", data=account)


@router.get("", response_model=ApiResponse)
async def list_accounts(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    is_admin = current_user.role == "admin"
    if is_admin:
        target_id = employeeId  # None = all accounts (admin overview)
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_id = employee["id"]

    accounts = await service.list_accounts(target_id, is_admin)
    return ApiResponse(message="Email accounts fetched", data=accounts)


@router.get("/{account_id}", response_model=ApiResponse)
async def get_account(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    account = await service.get_account(account_id, employee_id, is_admin)
    return ApiResponse(message="Account fetched", data=account)


@router.patch("/{account_id}", response_model=ApiResponse)
async def update_account(
    account_id: str,
    payload: EmailAccountUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    account = await service.update_account(account_id, employee_id, is_admin, payload)
    return ApiResponse(message="Account updated", data=account)


@router.delete("/{account_id}", response_model=ApiResponse)
async def delete_account(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    await service.delete_account(account_id, employee_id, is_admin)
    return ApiResponse(message="Account deleted")


@router.post("/{account_id}/test", response_model=ApiResponse)
async def test_connection(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Verify SMTP credentials by doing a live login. No email is sent."""
    employee_id, is_admin = await _resolve_employee(current_user)
    result = await service.test_connection(account_id, employee_id, is_admin)
    return ApiResponse(
        message=result["message"],
        data=result,
        success=result["success"],
    )
