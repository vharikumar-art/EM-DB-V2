from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class EmailMasterOut(BaseModel):
    id: str
    employeeId: str
    uploadBatch: str
    isDuplicate: bool
    fullName: str = ""
    email: str
    university: str = ""
    website: str = ""
    country: str = ""
    state: str = ""
    city: str = ""
    domain: str = ""
    domain_group: list[str] = Field(default_factory=list)
    industry: str = ""
    designation: str = ""
    phone: str = ""
    linkedin: str = ""
    citation: str = ""
    mailSource: str = ""
    # Employee usage tracking
    uploadedByName: str | None = None
    usedByEmployeeIds: list[str] = Field(default_factory=list)
    usedByEmployeeNames: list[str] = Field(default_factory=list)
    inProfileEmails: bool = False
    usageCount: int = 0
    lastUsedAt: str | None = None
    assignedDate: str | None = None
    assignedProfiles: list[dict] = Field(default_factory=list)
    hasReply: bool = False
    replyReason: str | None = None
    replyCustomReason: str | None = None
    replyMarkedAt: str | None = None
    replyMarkedBy: str | None = None
    replyMarkedByName: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class UploadResult(BaseModel):
    totalUploaded: int
    unique: int
    duplicate: int
    failed: int
    uploadBatch: str
    failedEmails: list[dict] = Field(default_factory=list)


class EmailMasterFilterQuery(BaseModel):
    country: list[str] | None = None
    domain: list[str] | None = None
    university: list[str] | None = None
    includeDuplicates: bool = False


ReplyReason = Literal["replied", "converted", "other"]


class MarkReplyRequest(BaseModel):
    email: EmailStr
    reason: ReplyReason
    customReason: str | None = None

    @model_validator(mode="after")
    def validate_custom_reason(self):
        if self.reason == "other" and not self.customReason:
            raise ValueError("customReason is required when reason is 'other'")
        if self.reason != "other" and self.customReason:
            raise ValueError("customReason is only allowed when reason is 'other'")
        return self


class UpdateReplyRequest(BaseModel):
    hasReply: bool | None = None
    reason: ReplyReason | None = None
    customReason: str | None = None

    @model_validator(mode="after")
    def validate_custom_reason(self):
        if self.reason == "other" and not self.customReason:
            raise ValueError("customReason is required when reason is 'other'")
        if self.reason is not None and self.reason != "other" and self.customReason:
            raise ValueError("customReason is only allowed when reason is 'other'")
        return self
