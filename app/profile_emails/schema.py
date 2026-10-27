from pydantic import BaseModel, Field

from app.profile_emails.model import ProfileEmailType, SendStatus


class ProfileEmailOut(BaseModel):
    id: str
    profileId: str
    employeeId: str
    campaignId: str | None = None
    mailType: ProfileEmailType = ProfileEmailType.DRAFT
    masterEmailId: str
    fullName: str = ""
    email: str
    university: str = ""
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
    draftSubject: str | None = None
    draftMessageId: str | None = None
    draftSentDate: str | None = None
    reminderSubject: str | None = None
    reminderMessageId: str | None = None
    reminderSentDate: str | None = None
    sentDate: str | None = None
    errorMessage: str | None = None
    notes: str = ""
    retryCount: int = 0
    createdAt: str | None = None
    updatedAt: str | None = None


class ProfileEmailUpdate(BaseModel):
    """Fields an employee can manually edit on a profile email row."""
    fullName: str | None = None
    university: str | None = None
    country: str | None = None
    notes: str | None = None
    sendStatus: SendStatus | None = None


class GenerateListRequest(BaseModel):
    """
    Optional override filters when generating a profile email list.
    If omitted, profile's stored filters are used.
    """
    overrideFilters: dict | None = None
    allowUsed: bool = Field(
        default=False,
        description="If True, allow fetching emails that have been previously used (usageCount > 0) but are not currently locked in a profile"
    )


class ProfileEmailTypeStats(BaseModel):
    total: int
    pending: int
    sending: int
    sent: int
    failed: int
    skipped: int


class ProfileEmailStats(ProfileEmailTypeStats):
    byType: dict[ProfileEmailType, ProfileEmailTypeStats]
