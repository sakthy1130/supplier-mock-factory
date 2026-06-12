"""Quickwit index name resolution. Port from QuickwitHotelKeyChangeReportWrapper."""

from __future__ import annotations

from datetime import date, datetime


def resolve_console_logs_index(
    quickwit_base_url: str,
    *,
    on_date: date | None = None,
) -> str:
    """Staging: hotels-consolelogs-staging-YYYY_MM_DD. Prod: hotels-consolelogs-prod-apps-YYYY_MM."""
    day = on_date or datetime.now().date()
    if "quickwit-prod" in quickwit_base_url:
        return f"hotels-consolelogs-prod-apps-{day.strftime('%Y_%m')}"
    return f"hotels-consolelogs-staging-{day.strftime('%Y_%m_%d')}"
