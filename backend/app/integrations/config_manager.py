"""Config manager cache API. Port from ClearApiKeyCacheActivator."""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.integrations.backoffice import BackofficeClient, BackofficeError


class ConfigManagerClient:
    def __init__(self, backoffice: BackofficeClient | None = None) -> None:
        self.settings = get_settings()
        self.backoffice = backoffice or BackofficeClient()
        # Java ClearApiKeyCacheActivator uses backoffice base URL, not config manager host.
        self.base_url = self.settings.backoffice_url.rstrip("/")

    async def clear_api_key_cache(self, api_key: str) -> None:
        """POST /api/v1/cache/config/clear/{apiKey} on backoffice/config host."""
        headers = await self.backoffice.auth_headers()
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/cache/config/clear/{api_key}",
                headers=headers,
            )
        if response.status_code != 200:
            raise BackofficeError(
                f"Clear apiKey cache failed status={response.status_code} body={response.text}"
            )
