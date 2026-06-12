"""Log search APIs — Quickwit (runtime)."""

from fastapi import APIRouter

from app.models.quickwit import QuickwitSearchRequest, QuickwitSearchResponse
from app.services.quickwit_service import run_quickwit_search_http

router = APIRouter(prefix="/logs", tags=["logs"])


@router.post("/quickwit/search", response_model=QuickwitSearchResponse)
async def quickwit_search(request: QuickwitSearchRequest) -> QuickwitSearchResponse:
    """Search Quickwit console logs (staging index auto-resolved by date)."""
    return await run_quickwit_search_http(
        request.query,
        index=request.index,
        minutes=request.minutes,
        max_hits=request.max_hits,
    )
