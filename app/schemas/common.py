from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "OK"
    data: T | None = None
    options: dict | None = None  # For dropdown options in responses


class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "OK"
    data: list[T]
    total: int
    page: int
    pageSize: int
    totalPages: int


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=25, ge=1, le=500)

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.pageSize
