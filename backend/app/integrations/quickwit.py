"""Quickwit logs search client. Port from QuickwitLogsActivator + QuickwitLogsWrapper."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_SORT = "+fluentbit_timestamp"
QA_USER_AGENT = "qa_automation"


class QuickwitError(RuntimeError):
    pass


class QuickwitClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        base = self.settings.quickwit_logs_api_url.rstrip("/")
        self.base_url = base
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "QuickwitClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True
        return self._client

    def _search_url(self, index: str) -> str:
        if not self.base_url:
            raise QuickwitError("QUICKWIT_LOGS_API_URL not configured")
        return f"{self.base_url}/{index}/search"

    async def search(
        self,
        index: str,
        query: str,
        *,
        max_hits: int = 10_000,
        start_timestamp: int,
        end_timestamp: int | None = None,
        sort_by_field: str = DEFAULT_SORT,
    ) -> dict[str, Any]:
        """POST /{index}/search — returns {status, body} like Java activator."""
        body: dict[str, Any] = {
            "query": query,
            "max_hits": max_hits,
            "start_timestamp": start_timestamp,
            "sort_by_field": sort_by_field,
        }
        if end_timestamp is not None:
            body["end_timestamp"] = end_timestamp

        client = self._get_client()
        response = await client.post(
            self._search_url(index),
            json=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "*/*",
                "x-user-agent": QA_USER_AGENT,
            },
        )
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text}

        return {"status": response.status_code, "body": payload}

    async def search_last_minutes(
        self,
        index: str,
        query: str,
        minutes: int,
        *,
        max_hits: int = 3_000,
    ) -> dict[str, Any]:
        start_ts = int(time.time()) - minutes * 60
        result = await self.search(index, query, max_hits=max_hits, start_timestamp=start_ts)
        _raise_on_failure(result, index, query)
        return result

    async def search_last_hours(
        self,
        index: str,
        query: str,
        hours: int,
        *,
        max_hits: int = 10_000,
    ) -> dict[str, Any]:
        start_ts = int(time.time()) - hours * 3600
        result = await self.search(index, query, max_hits=max_hits, start_timestamp=start_ts)
        _raise_on_failure(result, index, query)
        return result


def extract_hits(quickwit_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse hits from activator-style {status, body:{hits:[]}} or bare body."""
    body = quickwit_response.get("body")
    if isinstance(body, dict) and isinstance(body.get("hits"), list):
        return [hit for hit in body["hits"] if isinstance(hit, dict)]
    hits = quickwit_response.get("hits")
    if isinstance(hits, list):
        return [hit for hit in hits if isinstance(hit, dict)]
    return []


def hit_count(quickwit_response: dict[str, Any]) -> int:
    hits = extract_hits(quickwit_response)
    if hits:
        return len(hits)
    body = quickwit_response.get("body")
    if isinstance(body, dict) and isinstance(body.get("num_hits"), int):
        return body["num_hits"]
    return 0


def _raise_on_failure(result: dict[str, Any], index: str, query: str) -> None:
    status = result.get("status")
    if status != 200:
        raise QuickwitError(
            f"Quickwit search failed status={status} index={index} query={query!r}"
        )
