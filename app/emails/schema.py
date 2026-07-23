from pydantic import BaseModel, Field


class EmailRecordOut(BaseModel):
    id: str
    employeeId: str
    uploadedByName: str | None = None
    fullName: str
    email: str
    company: str
    website: str
    country: str
    state: str
    city: str
    domain: str
    industry: str
    designation: str
    phone: str
    linkedin: str
    uploadBatch: str
    isDuplicate: bool
    createdAt: str | None = None


class UploadResult(BaseModel):
    totalUploaded: int
    unique: int
    duplicate: int
    failed: int
    uploadBatch: str


class EmailFilterQuery(BaseModel):
    country: list[str] | None = None
    domain: list[str] | None = None
    industry: list[str] | None = None
    type: list[str] | None = None
    includeDuplicates: bool = False


class InsertDuplicatesOption(BaseModel):
    insertDuplicates: bool = Field(
        default=False, description="If true, duplicate rows are still inserted but flagged isDuplicate=true"
    )
