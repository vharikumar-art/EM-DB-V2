from pydantic import BaseModel, Field

from app.campaigns.model import CampaignStatus


class CampaignStartRequest(BaseModel):
    profileId: str
    campaignName: str = Field(default="", max_length=200)
    dailyLimit: int | None = Field(default=None, ge=1, le=10000, description="Daily email limit for this campaign (required, not optional)")
    limitOverride: int | None = Field(default=None, ge=1, le=10000, description="[DEPRECATED] Use dailyLimit instead")


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
    dailyLimit: int | None = None
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
