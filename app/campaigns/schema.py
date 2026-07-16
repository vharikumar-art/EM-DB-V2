from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from app.campaigns.model import CampaignStatus


class CampaignStartRequest(BaseModel):
    profileId: str
    campaignName: str = Field(default="", max_length=200)
    dailyLimit: int | None = Field(default=None, ge=1, le=10000, description="Daily email limit for this campaign (required, not optional)")
    limitOverride: int | None = Field(default=None, ge=1, le=10000, description="[DEPRECATED] Use dailyLimit instead")


class CampaignScheduleRequest(BaseModel):
    """Request to create a scheduled campaign"""
    profileId: str
    campaignName: str = Field(default="", max_length=200)
    scheduledFor: datetime = Field(description="UTC datetime when campaign should run")
    dailyLimit: int | None = Field(default=None, ge=1, le=10000, description="Daily email limit")
    maxRetries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts if campaign fails")
    
    @field_validator('scheduledFor')
    @classmethod
    def validate_scheduled_for(cls, v: datetime) -> datetime:
        """Ensure scheduled_for is in the future"""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        if v <= now:
            raise ValueError("scheduled_for must be in the future")
        return v


class SchedulerProcessResponse(BaseModel):
    """Response from processing scheduled campaigns"""
    total_checked: int = Field(description="Total campaigns checked")
    total_executed: int = Field(description="Total campaigns executed")
    successful: int = Field(description="Successful executions")
    failed: int = Field(description="Failed executions")
    errors: list[dict] = Field(description="Error details for failed campaigns")
    execution_duration_ms: float = Field(description="Total execution time in milliseconds")
    execution_start: str = Field(description="ISO 8601 start time")
    execution_end: str | None = Field(description="ISO 8601 end time")


class SchedulerStatusResponse(BaseModel):
    """Response from scheduler status endpoint"""
    current_time: str = Field(description="Current UTC time (ISO 8601)")
    campaigns_awaiting_execution: int = Field(description="Campaigns due but not yet executed")
    campaigns_currently_processing: int = Field(description="Campaigns currently being processed")
    campaigns_completed_24h: int = Field(description="Campaigns completed in last 24 hours")
    campaigns_failed_24h: int = Field(description="Campaigns failed in last 24 hours")
    health: str = Field(description="Scheduler health status: healthy/warning/critical")


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
    # Scheduling fields
    scheduledFor: str | None = None
    processingStartedAt: str | None = None
    executionDuration: float | None = None
    errorMessage: str | None = None
    retryCount: int = 0
    maxRetries: int = 3


class CampaignStatusUpdate(BaseModel):
    """Internal payload used by the campaign engine to push counter updates."""
    sent: int = 0
    failed: int = 0
    skipped: int = 0
