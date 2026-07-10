from datetime import datetime

from pydantic import BaseModel

from app.logs.model import LogAction


class LogOut(BaseModel):
    id: str
    employeeId: str
    profileId: str | None = None
    action: LogAction
    uploadedCount: int
    uniqueCount: int
    duplicateCount: int
    sentCount: int
    runDate: str | None = None
    createdAt: str | None = None


class CampaignLogUpdate(BaseModel):
    """Payload n8n sends back after a campaign run to update sent counts."""
    profileId: str
    sentCount: int
    runDate: datetime
