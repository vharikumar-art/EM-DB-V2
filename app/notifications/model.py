from datetime import datetime, timezone
from typing import Any

from app.notifications.schema import NotificationType


def build_notification_document(
    employee_id: str,
    message: str,
    type: NotificationType,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "employeeId": employee_id,
        "message": message,
        "type": type.value,
        "isRead": False,
        "createdAt": now,
    }
