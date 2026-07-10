from pydantic import BaseModel, Field

from app.campaigns.model import CampaignStatus


class CampaignStartRequest(BaseModel):
    profileId: str
    campaignName: str = Field(default="", max_length=200)
    limitOverride: int | None = Field(default=None, ge=1, le=10000, description="Optional limit to override profile's dailyLimit for this campaign")


class CampaignOut(BaseModel):
    id: str
    campaignName: str
    profileId: str
    employeeId: str
    status: CampaignStatus
    totalEmails: int
    pending: int
    sent: int
    failed: int
    skipped: int
    replies: int
    limitOverride: int | None = None
    startedAt: str | None = None
    completedAt: str | None = None
    pausedAt: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class CampaignStatusUpdate(BaseModel):
    """Internal payload used by the campaign engine to push counter updates."""
    sent: int = 0
    failed: int = 0
    skipped: int = 0
