"""Quickwit index name resolution. Port from QuickwitHotelKeyChangeReportWrapper.

Dev and stg share the same Quickwit URL (only the index prefix differs), so the
index can no longer be picked by inspecting the base URL — it must be resolved
from the active env instead.
"""

from __future__ import annotations

from datetime import date, datetime

# SMF env code -> Quickwit index prefix (they differ for stg: "stg" vs "staging").
_ENV_INDEX_PREFIX: dict[str, str] = {
    "dev": "dev",
    "stg": "staging",
}


def resolve_console_logs_index(
    env: str,
    *,
    on_date: date | None = None,
) -> str:
    """dev/stg: hotels-consolelogs-{prefix}-YYYY_MM_DD (daily).
    prod: hotels-consolelogs-prod-apps-YYYY_MM (monthly).
    """
    day = on_date or datetime.now().date()
    if env == "prod":
        return f"hotels-consolelogs-prod-apps-{day.strftime('%Y_%m')}"
    prefix = _ENV_INDEX_PREFIX.get(env, env)
    return f"hotels-consolelogs-{prefix}-{day.strftime('%Y_%m_%d')}"
