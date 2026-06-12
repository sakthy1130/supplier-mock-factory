"""Enigma logs API client. Port from LogS3Wrapper."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings

LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

MAX_RETRIES = 15
RETRY_DELAY_SEC = 3.0

logger = logging.getLogger(__name__)


def normalize_and_concat_url(base_url: str, path: str) -> str:
    if not base_url.endswith("="):
        if not base_url.endswith("/"):
            base_url += "/"
    if path.startswith("/"):
        path = path[1:]
    return base_url + path


class LogsApiClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.logs_api_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "LogsApiClient":
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

    async def list_logs(self, sid: str) -> dict:
        """GET /api/logs/list/{sid} with retries."""
        url = f"{self.base_url}/api/logs/list/{sid}"
        return await self._get_with_retries(url, f"list logs for sid={sid}")

    async def get_log_detail(self, log_url: str) -> dict:
        """Fetch single log document via /api/logs/details?file=."""
        url = normalize_and_concat_url(f"{self.base_url}/api/logs/details?file=", log_url)
        return await self._get_with_retries(url, f"log detail for {log_url}")

    async def _get_with_retries(self, url: str, label: str) -> dict:
        client = self._get_client()
        last_status: int | None = None
        for attempt in range(MAX_RETRIES):
            response = await client.get(url, headers={"Accept": "application/json"})
            if response.status_code == 200:
                return response.json()
            last_status = response.status_code
            logger.warning(
                "Logs API %s failed (status=%s), attempt %s/%s",
                label,
                response.status_code,
                attempt + 1,
                MAX_RETRIES,
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY_SEC)
        raise RuntimeError(
            f"Failed to {label} after {MAX_RETRIES} attempts (last status={last_status})"
        )
