from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

from app.campaigns.model import CampaignStatus


class CampaignStartRequest(BaseModel):
    profileId: str
    mailType: Literal["draft", "reminder"] = Field(
        default="draft",
        description="Send pending draft emails or queued reminder emails",
    )
    campaignName: str = Field(default="", max_length=200)
    dailyLimit: int | None = Field(default=None, ge=1, le=10000, description="Daily email limit for this campaign (required, not optional)")
    limitOverride: int | None = Field(default=None, ge=1, le=10000, description="[DEPRECATED] Use dailyLimit instead")
    autoReminderEnabled: bool = Field(
        default=True,
        description="Automatically schedule a reminder after a draft campaign completes",
    )
    reminderDelayDays: int = Field(
        default=6,
        ge=1,
        le=15,
        description="Days after draft completion before the automatic reminder runs",
    )

    @field_validator("reminderDelayDays", mode="before")
    @classmethod
    def default_empty_reminder_delay(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return 6
        return value


class CampaignScheduleRequest(BaseModel):
    """Request to create a scheduled campaign"""
    profileId: str
    mailType: Literal["draft", "reminder"] = Field(
        default="draft",
        description="Send pending draft emails or queued reminder emails",
    )
    campaignName: str = Field(default="", max_length=200)
    scheduledDateLocal: str | None = Field(default=None, description="Local date string (YYYY-MM-DD), required for 'once'")
    scheduledTimeLocal: str = Field(description="Local time string (HH:MM)")
    timezoneOffsetMinutes: int = Field(description="Browser timezone offset in minutes (e.g., -330 for IST UTC+5:30)")
    dailyLimit: int | None = Field(default=None, ge=1, le=10000, description="Daily email limit")
    maxRetries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts if campaign fails")
    recurrenceType: str = Field(default="once", description="Recurrence type: 'once', 'daily', or 'weekly'")
    recurrenceDays: list[int] = Field(default_factory=list, description="Days for weekly recurrence (0=Mon, 6=Sun)")
    recurrenceEndDate: str | None = Field(default=None, description="End date for recurring campaigns (YYYY-MM-DD)")
    autoReminderEnabled: bool = Field(
        default=True,
        description="Automatically schedule a reminder after a draft campaign completes",
    )
    reminderDelayDays: int = Field(
        default=6,
        ge=1,
        le=15,
        description="Days after draft completion before the automatic reminder runs",
    )

    @field_validator("reminderDelayDays", mode="before")
    @classmethod
    def default_empty_reminder_delay(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return 6
        return value


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
    mailType: Literal["draft", "reminder"] = "draft"
    employeeId: str
    status: CampaignStatus
    totalEmails: int
    pending: int
    sent: int
    failed: int
    skipped: int
    replies: int
    processedEmails: int = 0
    progressPercent: float = 0
    dailyLimit: int | None = None
    limitOverride: int | None = None
    startedAt: str | None = None
    startedAtDisplay: str | None = None
    completedAt: str | None = None
    pausedAt: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    # Scheduling fields
    scheduledFor: str | None = None
    scheduledForDisplay: str | None = None
    processingStartedAt: str | None = None
    executionDuration: float | None = None
    errorMessage: str | None = None
    retryCount: int = 0
    maxRetries: int = 3
    autoReminderEnabled: bool = True
    reminderDelayDays: int = 6
    reminderAutomationStatus: str | None = None
    reminderAutomationError: str | None = None
    reminderCampaignId: str | None = None
    reminderScheduledFor: str | None = None
    # Recurrence fields
    recurrenceType: str = "once"
    recurrenceDays: list[int] = []
    recurrenceEndDate: str | None = None


class CampaignStatusUpdate(BaseModel):
    """Internal payload used by the campaign engine to push counter updates."""
    sent: int = 0
    failed: int = 0
    skipped: int = 0
