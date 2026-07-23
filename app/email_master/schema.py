from pydantic import BaseModel, Field


class EmailMasterOut(BaseModel):
    id: str
    employeeId: str
    uploadBatch: str
    isDuplicate: bool
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
    citation: str = ""
    mailSource: str = ""
    # Employee usage tracking
    uploadedByName: str | None = None
    usedByEmployeeId: str | None = None
    usedByEmployeeName: str | None = None
    inProfileEmails: bool = False
    assignedDate: str | None = None
    assignedProfiles: list[dict] = Field(default_factory=list)
    createdAt: str | None = None
    updatedAt: str | None = None


class UploadResult(BaseModel):
    totalUploaded: int
    unique: int
    duplicate: int
    failed: int
    uploadBatch: str


class EmailMasterFilterQuery(BaseModel):
    country: list[str] | None = None
    domain: list[str] | None = None
    industry: list[str] | None = None
    company: list[str] | None = None
    includeDuplicates: bool = False
