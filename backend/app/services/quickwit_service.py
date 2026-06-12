"""Quickwit search helpers shared by logs + scenarios routes."""

from __future__ import annotations

from fastapi import HTTPException

from app.config import get_settings
from app.core.quickwit_indices import resolve_console_logs_index
from app.integrations.quickwit import QuickwitClient, QuickwitError, extract_hits, hit_count
from app.models.quickwit import QuickwitSearchResponse


def require_quickwit_url() -> str:
    url = get_settings().quickwit_logs_api_url.strip()
    if not url:
        raise HTTPException(
            status_code=503,
            detail="QUICKWIT_LOGS_API_URL not configured in backend/.env",
        )
    return url.rstrip("/")


async def run_quickwit_search(
    query: str,
    *,
    index: str | None,
    minutes: int,
    max_hits: int,
) -> QuickwitSearchResponse:
    settings = get_settings()
    base_url = settings.quickwit_logs_api_url.rstrip("/")
    if not base_url:
        raise QuickwitError("QUICKWIT_LOGS_API_URL not configured")

    resolved_index = index or resolve_console_logs_index(base_url)

    async with QuickwitClient() as client:
        raw = await client.search_last_minutes(
            resolved_index,
            query,
            minutes,
            max_hits=max_hits,
        )

    return QuickwitSearchResponse(
        index=resolved_index,
        query=query,
        minutes=minutes,
        status=int(raw.get("status", 0)),
        num_hits=hit_count(raw),
        hits=extract_hits(raw),
    )


async def run_quickwit_search_http(
    query: str,
    *,
    index: str | None,
    minutes: int,
    max_hits: int,
) -> QuickwitSearchResponse:
    require_quickwit_url()
    try:
        return await run_quickwit_search(
            query,
            index=index,
            minutes=minutes,
            max_hits=max_hits,
        )
    except QuickwitError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
