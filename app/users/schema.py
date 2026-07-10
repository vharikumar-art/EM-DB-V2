from pydantic import BaseModel, EmailStr, Field

from app.users.model import UserRole, UserStatus


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.EMPLOYEE
    branch: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    status: UserStatus | None = None
    branch: str | None = None


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    password: str | None = None
    role: UserRole
    status: UserStatus
    branch: str | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
