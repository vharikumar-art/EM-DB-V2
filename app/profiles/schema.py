from pydantic import BaseModel, EmailStr, Field


class ProfileFilters(BaseModel):
    country: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    industry: list[str] = Field(default_factory=list)
    company: list[str] = Field(default_factory=list)
    type: list[str] = Field(default_factory=list)  # maps to designation / industry


class ProfileSendingOptions(BaseModel):
    dailyLimit: int = Field(default=100, ge=1, le=5000)
    delayMin: int = Field(default=30, ge=0, description="Minimum delay between sends in seconds")
    delayMax: int = Field(default=90, ge=0, description="Maximum delay between sends in seconds")


class FilterLimitConfig(BaseModel):
    limit: int = Field(default=0, ge=0, description="Maximum number of emails to fetch from filtered results (0 = no limit)")


class PromptSettings(BaseModel):
    personalizeGreeting: bool = True
    improveGrammar: bool = True
    improveProfessionalism: bool = False
    aiRewrite: bool = False
    customInstruction: str = ""


class Attachment(BaseModel):
    """File attachment for profile"""
    filename: str = Field(description="Original filename (e.g., document.pdf)")
    filepath: str = Field(description="Server path to file (e.g., uploads/templates/abc123_document.pdf)")
    size: int = Field(description="File size in bytes")


class Template(BaseModel):
    """Template model for A/B testing"""
    name: str = Field(default="", max_length=100, description="Template name (e.g., 'Aggressive', 'Friendly')")
    subject: str = Field(default="", max_length=500, description="Email subject line")
    body: str = Field(default="", description="Email body content")
    weight: int = Field(default=1, ge=1, le=100, description="Selection weight (higher = more likely)")


class ProfileCreate(BaseModel):
    profileName: str = Field(min_length=1, max_length=100)
    gmailAccount: EmailStr
    signature: str = Field(default="", description="HTML signature appended to every email")
    templates: list[Template] = Field(min_length=1, max_length=3, description="1-3 A/B testing templates (required)")
    attachments: list[Attachment] = Field(default_factory=list, description="File attachments (sent with all templates)")
    filters: ProfileFilters = Field(default_factory=ProfileFilters)
    filterLimit: int = Field(default=0, ge=0, description="Maximum emails to fetch from filtered results (0 = no limit)")
    sendingOptions: ProfileSendingOptions = Field(default_factory=ProfileSendingOptions)
    promptSettings: PromptSettings = Field(default_factory=PromptSettings)


class ProfileUpdate(BaseModel):
    profileName: str | None = None
    gmailAccount: EmailStr | None = None
    signature: str | None = None
    templates: list[Template] | None = None
    filters: ProfileFilters | None = None
    filterLimit: int | None = None
    sendingOptions: ProfileSendingOptions | None = None
    promptSettings: PromptSettings | None = None


class ProfileOut(BaseModel):
    id: str
    employeeId: str
    profileName: str
    gmailAccount: str
    signature: str
    templates: list[Template]
    attachments: list[Attachment] = Field(default_factory=list, description="File attachments (sent with all templates)")
    isActive: bool
    filters: ProfileFilters
    filterLimit: int
    sendingOptions: ProfileSendingOptions
    promptSettings: PromptSettings
    createdAt: str | None = None
    updatedAt: str | None = None


class TemplateAdd(BaseModel):
    """Add a new template to a profile"""
    name: str = Field(min_length=1, max_length=100, description="Template name (e.g., 'Aggressive', 'Friendly')")
    subject: str = Field(min_length=1, max_length=500, description="Email subject line")
    body: str = Field(min_length=1, description="Email body content")
    weight: int = Field(default=1, ge=1, le=100, description="Selection weight (higher = more likely)")


class TemplateUpdate(BaseModel):
    """Update an existing template"""
    name: str | None = None
    subject: str | None = None
    body: str | None = None
    weight: int | None = Field(default=None, ge=1, le=100)


class TemplateDelete(BaseModel):
    """Delete a template"""
    templateId: str = Field(description="ID of template to delete")
