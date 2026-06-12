"""Pydantic models for Quickwit log search."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class QuickwitSearchRequest(BaseModel):
    query: str = Field(min_length=1, description="Quickwit query string")
    index: Optional[str] = Field(
        default=None,
        description="Index name; auto-resolved from QUICKWIT_LOGS_API_URL when omitted",
    )
    minutes: int = Field(default=60, ge=1, le=24 * 60)
    max_hits: int = Field(default=3_000, ge=1, le=10_000)


class QuickwitSearchResponse(BaseModel):
    index: str
    query: str
    minutes: int
    status: int
    num_hits: int
    hits: list[dict[str, Any]] = Field(default_factory=list)
