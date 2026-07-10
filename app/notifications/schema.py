from enum import Enum
from pydantic import BaseModel


class NotificationType(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


class NotificationCreate(BaseModel):
    message: str
    type: NotificationType = NotificationType.INFO


class NotificationOut(BaseModel):
    id: str
    employeeId: str
    message: str
    type: NotificationType
    isRead: bool
    createdAt: str | None = None
