from pydantic import BaseModel, Field


class SettingCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, description="Setting list name, e.g. branch, department, city")
    values: list[str] = Field(..., min_length=1, description="List of dropdown values for this setting")


class SettingUpdate(BaseModel):
    key: str | None = None
    values: list[str] | None = None


class SettingOut(BaseModel):
    id: str
    key: str | None = None
    values: list[str] | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
