from typing import Any

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Common pagination query parameters."""

    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Field(default=50, ge=1, le=500, description="Items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Problem(BaseModel):
    """RFC 7807 Problem Details response."""

    type: str = Field(default="about:blank", description="URI identifying the problem type")
    title: str = Field(description="Short human-readable summary")
    status: int = Field(description="HTTP status code")
    detail: str | None = Field(default=None, description="Detailed explanation")
    instance: str | None = Field(default=None, description="URI of the specific occurrence")
    extensions: dict[str, Any] | None = Field(
        default=None, description="Additional problem-specific fields"
    )

    model_config = {"populate_by_name": True}


class PagedResponse(BaseModel):
    """Generic paged list wrapper."""

    total: int
    page: int
    page_size: int
    items: list[Any]
