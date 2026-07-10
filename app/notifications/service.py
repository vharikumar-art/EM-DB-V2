from app.core.exceptions import NotFoundException
from app.database.mongodb import get_collection
from app.notifications.model import build_notification_document
from app.notifications.schema import NotificationType
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "notifications"


from app.notifications.websocket import manager

async def _get_all_admin_user_ids() -> list[str]:
    """Return user_ids of all admin users (used to fan-out notifications)."""
    from app.database.mongodb import get_collection as _gc
    users = _gc("users")
    cursor = users.find({"role": "admin"}, {"_id": 1})
    return [str(doc["_id"]) async for doc in cursor]


async def create_notification(employee_id: str, message: str, type: NotificationType) -> dict:
    notifications = get_collection(COLLECTION)

    # --- Save and push to the originating employee/channel ---
    doc = build_notification_document(employee_id, message, type)
    result = await notifications.insert_one(doc)
    created = await notifications.find_one({"_id": result.inserted_id})
    notification = serialize_doc(created)
    await manager.send_personal_message(notification, employee_id)

    # --- Fan-out: also save + push live to every admin ---
    admin_ids = await _get_all_admin_user_ids()
    for admin_user_id in admin_ids:
        # Skip if the notification was already sent on this channel
        # (e.g. the originating action was done by the admin themselves)
        if admin_user_id == employee_id:
            continue
        admin_doc = build_notification_document(admin_user_id, message, type)
        await notifications.insert_one(admin_doc)
        # Push live — manager uses user_id as channel_id for admins
        await manager.send_personal_message(notification, admin_user_id)

    return notification



async def list_notifications(employee_id: str, unread_only: bool = False, limit: int = 50) -> list[dict]:
    notifications = get_collection(COLLECTION)
    query: dict = {"employeeId": employee_id}
    if unread_only:
        query["isRead"] = False

    cursor = notifications.find(query).sort("createdAt", -1).limit(limit)
    return serialize_list([d async for d in cursor])


async def mark_as_read(notification_id: str, employee_id: str) -> dict:
    notifications = get_collection(COLLECTION)
    result = await notifications.find_one_and_update(
        {"_id": to_object_id(notification_id), "employeeId": employee_id},
        {"$set": {"isRead": True}},
        return_document=True,
    )
    if not result:
        raise NotFoundException("Notification not found")
    return serialize_doc(result)


async def mark_all_as_read(employee_id: str) -> dict:
    notifications = get_collection(COLLECTION)
    result = await notifications.update_many(
        {"employeeId": employee_id, "isRead": False},
        {"$set": {"isRead": True}}
    )
    return {"modifiedCount": result.modified_count}
