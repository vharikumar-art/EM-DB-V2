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
        if await _is_employee_in_admin_scope(employee_id, admin_user_id):
            admin_doc = build_notification_document(admin_user_id, message, type)
            result = await notifications.insert_one(admin_doc)
            admin_notification = await notifications.find_one({"_id": result.inserted_id})
            admin_notification = serialize_doc(admin_notification)
            await manager.send_personal_message(admin_notification, admin_user_id)

    return notification


async def _is_employee_in_admin_scope(employee_id: str, admin_user_id: str) -> bool:
    """Check if an employee is within an admin's scope (branch-based for full access admins).
    
    For full access admins: checks if the employee is in the same branch.
    For partial access admins: checks if the employee is directly assigned to this admin.
    Also always returns True if the admin's own employee record matches.
    """
    try:
        employees = get_collection("employees")
        users = get_collection("users")
        
        # Get the admin user to check their access level
        admin_user = await users.find_one({"_id": to_object_id(admin_user_id)}, {"accessLevel": 1})
        admin_access_level = (admin_user or {}).get("accessLevel", "full")
        
        # Get admin's own employee record
        admin_employee = await employees.find_one({"userId": admin_user_id})
        if not admin_employee:
            return False
        
        admin_emp_id = str(admin_employee.get("_id"))
        
        # Always allow admin to be notified for their own actions
        if admin_emp_id == employee_id:
            return True
        
        # Get the target employee
        employee = await employees.find_one({"_id": to_object_id(employee_id)})
        if not employee:
            return False
        
        if admin_access_level == "partial":
            # Partial admin: check direct assignment
            return str(employee.get("assignedToAdmin")) == admin_emp_id
        else:
            # Full admin: check same branch
            admin_branch = admin_employee.get("branch")
            if not admin_branch:
                admin_u = await users.find_one({"_id": to_object_id(admin_user_id)}, {"branch": 1})
                admin_branch = (admin_u or {}).get("branch")

            if not admin_branch:
                return False

            employee_branch = employee.get("branch")
            if not employee_branch and employee.get("userId"):
                emp_u = await users.find_one({"_id": to_object_id(str(employee["userId"]))}, {"branch": 1})
                employee_branch = (emp_u or {}).get("branch")

            return bool(
                employee_branch
                and str(admin_branch).strip().casefold() == str(employee_branch).strip().casefold()
            )
    except Exception:
        return False


# Backwards compatibility alias
_is_employee_assigned_to_admin = _is_employee_in_admin_scope



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
