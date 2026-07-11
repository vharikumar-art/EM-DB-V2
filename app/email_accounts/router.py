from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUser, get_current_user, resolve_employee_context
from app.core.exceptions import BadRequestException
from app.email_accounts import service
from app.email_accounts.schema import EmailAccountCreate, EmailAccountUpdate
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/email-accounts", tags=["Email Accounts"])


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: EmailAccountCreate,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a Gmail / SMTP account. The app-password is encrypted at rest immediately."""
    if current_user.role == "admin" and not employeeId:
        raise BadRequestException("Admins must specify employeeId")
    
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    account = await service.create_account(employee_id, payload)
    return ApiResponse(message="Email account added", data=account)


@router.get("", response_model=ApiResponse)
async def list_accounts(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List email accounts. Admins can specify employeeId to view any employee's accounts."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    accounts = await service.list_accounts(employee_id if employee_id else None, is_admin)
    return ApiResponse(message="Email accounts fetched", data=accounts)


@router.get("/{account_id}", response_model=ApiResponse)
async def get_account(
    account_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get single email account. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    account = await service.get_account(account_id, employee_id, is_admin)
    return ApiResponse(message="Account fetched", data=account)


@router.patch("/{account_id}", response_model=ApiResponse)
async def update_account(
    account_id: str,
    payload: EmailAccountUpdate,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update email account. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    account = await service.update_account(account_id, employee_id, is_admin, payload)
    return ApiResponse(message="Account updated", data=account)


@router.delete("/{account_id}", response_model=ApiResponse)
async def delete_account(
    account_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete email account. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    await service.delete_account(account_id, employee_id, is_admin)
    return ApiResponse(message="Account deleted")


@router.post("/{account_id}/test", response_model=ApiResponse)
async def test_connection(
    account_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Verify SMTP credentials by doing a live login. No email is sent. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    result = await service.test_connection(account_id, employee_id, is_admin)
    return ApiResponse(
        message=result["message"],
        data=result,
        success=result["success"],
    )
