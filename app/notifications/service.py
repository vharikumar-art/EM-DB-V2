from datetime import datetime, timezone, timedelta

from app.core.exceptions import NotFoundException
from app.database.mongodb import get_collection
from app.notifications.model import build_notification_document
from app.notifications.schema import NotificationType
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "notifications"

# Cache for super_admin and admin user IDs with TTL (60 seconds) to reduce database queries
_super_admin_cache: dict = {"ids": [], "expires_at": None}
_admin_cache: dict = {"ids": [], "expires_at": None}


from app.notifications.websocket import manager


async def _get_all_super_admin_user_ids() -> list[str]:
    """Return user_ids of all super_admin users.
    
    Results are cached for 60 seconds to reduce database load.
    """
    global _super_admin_cache
    now = datetime.now(timezone.utc)
    
    # Check if cache is still valid
    if _super_admin_cache["expires_at"] and now < _super_admin_cache["expires_at"]:
        return _super_admin_cache["ids"]
    
    # Cache expired or not set, fetch from database
    from app.database.mongodb import get_collection as _gc
    users = _gc("users")
    cursor = users.find({"role": "super_admin"}, {"_id": 1})
    super_admin_ids = [str(doc["_id"]) async for doc in cursor]
    
    # Update cache with 60-second TTL
    _super_admin_cache["ids"] = super_admin_ids
    _super_admin_cache["expires_at"] = now + timedelta(seconds=60)
    
    return super_admin_ids


async def _get_all_admin_user_ids() -> list[str]:
    """Return user_ids of all admin users (excludes super_admins).
    
    Results are cached for 60 seconds to reduce database load.
    """
    global _admin_cache
    now = datetime.now(timezone.utc)
    
    # Check if cache is still valid
    if _admin_cache["expires_at"] and now < _admin_cache["expires_at"]:
        return _admin_cache["ids"]
    
    # Cache expired or not set, fetch from database
    from app.database.mongodb import get_collection as _gc
    users = _gc("users")
    cursor = users.find({"role": "admin"}, {"_id": 1})
    admin_ids = [str(doc["_id"]) async for doc in cursor]
    
    # Update cache with 60-second TTL
    _admin_cache["ids"] = admin_ids
    _admin_cache["expires_at"] = now + timedelta(seconds=60)
    
    return admin_ids


async def create_notification(employee_id: str, message: str, type: NotificationType) -> dict:
    notifications = get_collection(COLLECTION)

    # --- Save and push to the originating employee/channel ---
    doc = build_notification_document(employee_id, message, type)
    result = await notifications.insert_one(doc)
    created = await notifications.find_one({"_id": result.inserted_id})
    notification = serialize_doc(created)
    await manager.send_personal_message(notification, employee_id)

    # --- Fan-out: save + push live to every SUPER_ADMIN ---
    # Super admins see ALL notifications
    super_admin_ids = await _get_all_super_admin_user_ids()
    for super_admin_id in super_admin_ids:
        if super_admin_id == employee_id:
            continue
        super_admin_doc = build_notification_document(super_admin_id, message, type)
        result = await notifications.insert_one(super_admin_doc)
        super_admin_notification = await notifications.find_one({"_id": result.inserted_id})
        super_admin_notification = serialize_doc(super_admin_notification)
        await manager.send_personal_message(super_admin_notification, super_admin_id)

    # --- Fan-out: save + push live to relevant ADMINS ---
    # Admins see notifications for employees assigned to them
    admin_ids = await _get_all_admin_user_ids()
    for admin_user_id in admin_ids:
        if admin_user_id == employee_id:
            continue
        # Check if this employee is assigned to this admin
        if await _is_employee_assigned_to_admin(employee_id, admin_user_id):
            admin_doc = build_notification_document(admin_user_id, message, type)
            result = await notifications.insert_one(admin_doc)
            admin_notification = await notifications.find_one({"_id": result.inserted_id})
            admin_notification = serialize_doc(admin_notification)
            await manager.send_personal_message(admin_notification, admin_user_id)

    return notification


async def _is_employee_assigned_to_admin(employee_id: str, admin_user_id: str) -> bool:
    """Check if an employee is assigned to an admin.
    
    This checks both direct assignment and admin's own employee record.
    """
    try:
        employees = get_collection("employees")
        # Check if employee is assigned to this admin
        employee = await employees.find_one({"_id": to_object_id(employee_id)})
        if employee and str(employee.get("assignedToAdmin")) == admin_user_id:
            return True
        # Also check if admin's own employee record matches
        admin_employee = await employees.find_one({"userId": admin_user_id})
        if admin_employee and str(admin_employee.get("_id")) == employee_id:
            return True
        return False
    except Exception:
        return False



async def list_notifications(employee_id: str, unread_only: bool = False, limit: int = 50) -> list[dict]:
    notifications = get_collection(COLLECTION)
    query: dict = {"employeeId": employee_id}
    if unread_only:
        query["isRead"] = False

    cursor = notifications.find(query).sort("createdAt", -1).limit(limit)
    return serialize_list([d async for d in cursor])


async def mark_as_read(notification_id: str, employee_id: str) -> dict:
    notifications = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    result = await notifications.find_one_and_update(
        {"_id": to_object_id(notification_id), "employeeId": employee_id},
        {"$set": {"isRead": True, "readAt": now}},
        return_document=True,
    )
    if not result:
        raise NotFoundException("Notification not found")
    return serialize_doc(result)


async def mark_all_as_read(employee_id: str) -> dict:
    notifications = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    result = await notifications.update_many(
        {"employeeId": employee_id, "isRead": False},
        {"$set": {"isRead": True, "readAt": now}}
    )
    return {"modifiedCount": result.modified_count}
