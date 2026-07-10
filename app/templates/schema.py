from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="")
    signature: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    isGlobal: bool = Field(
        default=False,
        description="Admin-only flag. Global templates are visible to all employees.",
    )


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    subject: str | None = None
    body: str | None = None
    signature: str | None = None
    tags: list[str] | None = None
    isGlobal: bool | None = None


class TemplateOut(BaseModel):
    id: str
    employeeId: str
    name: str
    subject: str
    body: str
    signature: str
    tags: list[str]
    isGlobal: bool
    usageCount: int
    createdAt: str | None = None
    updatedAt: str | None = None


class TemplatePreviewRequest(BaseModel):
    """
    Send a sample lead record to preview how placeholders will be resolved.
    """
    templateId: str
    sampleLead: dict = Field(
        default_factory=lambda: {
            "fullName": "John Doe",
            "company": "Acme Corp",
            "industry": "Technology",
            "designation": "CTO",
            "country": "USA",
        }
    )
