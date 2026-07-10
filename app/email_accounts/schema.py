from pydantic import BaseModel, EmailStr, Field

from app.email_accounts.model import AccountType


class EmailAccountCreate(BaseModel):
    email: EmailStr
    appPassword: str = Field(
        min_length=1,
        description="Gmail App Password or SMTP password. Stored encrypted, never returned in responses.",
    )
    displayName: str = Field(default="", max_length=100)
    accountType: AccountType = AccountType.GMAIL_SMTP
    smtpHost: str = Field(default="smtp.gmail.com")
    smtpPort: int = Field(default=587)
    useTls: bool = Field(default=True)


class EmailAccountUpdate(BaseModel):
    appPassword: str | None = Field(default=None, min_length=1)
    displayName: str | None = Field(default=None, max_length=100)
    smtpHost: str | None = None
    smtpPort: int | None = None
    useTls: bool | None = None
    isActive: bool | None = None


class EmailAccountOut(BaseModel):
    """
    Password fields are NEVER included in API responses.
    """
    id: str
    employeeId: str
    email: str
    displayName: str
    accountType: AccountType
    smtpHost: str
    smtpPort: int
    useTls: bool
    isActive: bool
    lastUsedAt: str | None = None
    lastErrorAt: str | None = None
    lastError: str | None = None
    sendCount: int
    createdAt: str | None = None
    updatedAt: str | None = None


class ConnectionTestResult(BaseModel):
    success: bool
    message: str
