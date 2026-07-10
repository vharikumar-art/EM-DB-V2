from pydantic import BaseModel, EmailStr, Field

from app.employees.model import EmployeeStatus

from app.users.model import UserRole

class EmployeeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.EMPLOYEE
    branch: str | None = None



class EmployeeUpdate(BaseModel):
    department: str | None = None
    branch: str | None = None
    status: EmployeeStatus | None = None



class EmployeeOut(BaseModel):
    id: str
    userId: str
    status: EmployeeStatus
    createdAt: str | None = None
    updatedAt: str | None = None
