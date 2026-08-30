"""Derby room catalogue via hotels-connectivity-adapter-misc.

hotels-derby-bts-adapter names every room it returns by looking the rate's ``roomId`` up
in this catalogue, per hotel. A rate whose roomId is not in it is dropped — silently,
with no error and an empty package list, which is indistinguishable from "the supplier
had no availability". A mock that invents room ids therefore passes search (which needs
only a hotel-level price) and returns zero packages.

Only HIL and CHC go through the Derby adapter; every other supplier ignores this.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class DerbyRoomsClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "DerbyRoomsClient":
        self._get_client()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    async def room_ids(self, hotel_code: str, supplier_id: str) -> list[str]:
        """Room ids the adapter will accept for this hotel, best-effort.

        Returns [] rather than raising: an unreachable catalogue must not fail scenario
        creation, it just leaves the template's captured room ids in place — the same
        behaviour as before this lookup existed.
        """
        base = (self.settings.adapter_misc_url or "").rstrip("/")
        if not base or not hotel_code or not supplier_id:
            return []
        url = f"{base}/derby/hotels/{hotel_code}/rooms"
        try:
            response = await self._get_client().get(
                url, params={"supplierId": supplier_id}, headers={"Accept": "application/json"}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Derby room catalogue lookup failed for %s: %s", hotel_code, exc)
            return []
        rooms = payload.get("rooms") if isinstance(payload, dict) else None
        if not isinstance(rooms, dict):
            return []
        # dicts preserve insertion order, so the catalogue's own order is kept and a
        # scenario's package N maps to the same room on every rebuild.
        return [str(key) for key in rooms if str(key).strip()]
