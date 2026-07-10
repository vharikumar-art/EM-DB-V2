from pydantic import BaseModel, Field

from app.profile_emails.model import SendStatus


class ProfileEmailOut(BaseModel):
    id: str
    profileId: str
    employeeId: str
    campaignId: str | None = None
    masterEmailId: str
    fullName: str = ""
    email: str
    company: str = ""
    website: str = ""
    country: str = ""
    state: str = ""
    city: str = ""
    domain: str = ""
    industry: str = ""
    designation: str = ""
    phone: str = ""
    linkedin: str = ""
    sendStatus: SendStatus = SendStatus.PENDING
    threadId: str | None = None
    messageId: str | None = None
    sentDate: str | None = None
    errorMessage: str | None = None
    notes: str = ""
    retryCount: int = 0
    createdAt: str | None = None
    updatedAt: str | None = None


class ProfileEmailUpdate(BaseModel):
    """Fields an employee can manually edit on a profile email row."""
    fullName: str | None = None
    company: str | None = None
    country: str | None = None
    notes: str | None = None
    sendStatus: SendStatus | None = None


class GenerateListRequest(BaseModel):
    """
    Optional override filters when generating a profile email list.
    If omitted, profile's stored filters are used.
    """
    overrideFilters: dict | None = None
    limitOverride: int | None = Field(default=None, ge=1, le=50000)


class ProfileEmailStats(BaseModel):
    total: int
    pending: int
    sent: int
    failed: int
    skipped: int
    sending: int
