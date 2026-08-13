from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.core.dependencies import CurrentUser, get_current_user
from app.core.security import decode_token
from app.employees.service import get_employee_by_user_id
from app.notifications import service
from app.notifications.websocket import manager
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/notifications", tags=["Notifications"])


async def _resolve_employee_id(current_user: CurrentUser, employee_id_query: str | None) -> str:
    """Resolve which employee's notifications the user is trying to view.
    
    - super_admin: can view any employee
    - admin: can view assigned employees only
    - employee: can only view own notifications
    """
    if current_user.role == "super_admin":
        # Super admin can view any employee's notifications
        return employee_id_query or current_user.user_id
    
    if current_user.role == "admin":
        # If an admin provides an employeeId, verify they manage that employee
        if employee_id_query:
            # Check if this employee is assigned to this admin
            from app.notifications.service import _is_employee_assigned_to_admin
            is_assigned = await _is_employee_assigned_to_admin(employee_id_query, current_user.user_id)
            if not is_assigned:
                from app.core.exceptions import ForbiddenException
                raise ForbiddenException("You do not have access to this employee's notifications")
            return employee_id_query
        # Otherwise, default to the admin's own notifications
        return current_user.user_id
    
    # Employee: only view own notifications
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"]


@router.websocket("/ws")
async def notifications_websocket(websocket: WebSocket, token: str = Query(...)):
    """
    WebSocket endpoint for live notifications.
    """
    try:
        payload = decode_token(token)
    except ValueError as exc:
        await websocket.close(code=1008)
        return

    if payload.get("type") != "access":
        await websocket.close(code=1008)
        return

    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or not role:
        await websocket.close(code=1008)
        return

    # For employees, scope to their own record; super_admins and admins stream on their userId channel
    if role in ("super_admin", "admin"):
        channel_id = user_id
        is_admin = True
    else:
        try:
            employee = await get_employee_by_user_id(user_id)
            channel_id = employee["id"]
            is_admin = False
        except Exception as e:
            # Employee record not found or deleted - gracefully close connection
            import logging
            logging.warning(f"Failed to resolve employee for user {user_id}: {str(e)}")
            await websocket.close(code=1008)
            return

    await manager.connect(websocket, channel_id, is_admin=is_admin)
    try:
        while True:
            # Keep connection alive; we don't expect messages from the client
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id)


@router.get("", response_model=ApiResponse)
async def list_notifications(
    employeeId: str | None = Query(default=None),
    unreadOnly: bool = Query(default=False),
    limit: int = Query(default=50),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id = await _resolve_employee_id(current_user, employeeId)
    notifications = await service.list_notifications(employee_id, unreadOnly, limit)
    return ApiResponse(message="Notifications fetched", data=notifications)


@router.patch("/read-all", response_model=ApiResponse)
async def mark_all_as_read(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id = await _resolve_employee_id(current_user, employeeId)
    result = await service.mark_all_as_read(employee_id)
    return ApiResponse(message="All notifications marked as read", data=result)


@router.patch("/{notification_id}/read", response_model=ApiResponse)
async def mark_as_read(
    notification_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id = await _resolve_employee_id(current_user, employeeId)
    notification = await service.mark_as_read(notification_id, employee_id)
    return ApiResponse(message="Notification marked as read", data=notification)
