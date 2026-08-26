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
    # UNVERIFIED. ODIS logs live on enigma-logs-sandbox.discoversaudi.sa; its index
    # naming has not been read off the real Quickwit yet. This mirrors the env code,
    # which is what the fallback below would produce anyway — stated explicitly so the
    # guess is visible. Confirm against the live index list before relying on ODIS log
    # queries; stg is the precedent for code and prefix differing.
    "odis": "odis",
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
