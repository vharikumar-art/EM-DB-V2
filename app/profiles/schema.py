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


class PromptSettings(BaseModel):
    personalizeGreeting: bool = True
    improveGrammar: bool = True
    improveProfessionalism: bool = False
    aiRewrite: bool = False
    customInstruction: str = ""


class ProfileCreate(BaseModel):
    profileName: str = Field(min_length=1, max_length=100)
    gmailAccount: EmailStr
    subject: str = Field(default="", max_length=500, description="Email subject line (supports [name], [company] placeholders)")
    body: str = Field(default="", description="Email body HTML/text (supports [name], [company] placeholders)")
    signature: str = Field(default="", description="HTML signature appended to every email")
    filters: ProfileFilters = Field(default_factory=ProfileFilters)
    sendingOptions: ProfileSendingOptions = Field(default_factory=ProfileSendingOptions)
    promptSettings: PromptSettings = Field(default_factory=PromptSettings)


class ProfileUpdate(BaseModel):
    profileName: str | None = None
    gmailAccount: EmailStr | None = None
    subject: str | None = None
    body: str | None = None
    signature: str | None = None
    filters: ProfileFilters | None = None
    sendingOptions: ProfileSendingOptions | None = None
    promptSettings: PromptSettings | None = None


class ProfileOut(BaseModel):
    id: str
    employeeId: str
    profileName: str
    gmailAccount: str
    subject: str
    body: str
    signature: str
    isActive: bool
    filters: ProfileFilters
    sendingOptions: ProfileSendingOptions
    promptSettings: PromptSettings
    createdAt: str | None = None
    updatedAt: str | None = None
