"""Crawla realtime API client."""

from __future__ import annotations

from typing import Any
from typing import Optional

import httpx

from app.config import get_settings
from app.models.crawla import (
    CrawlaAnchorPackagesResponse,
    CrawlaAnchorRequest,
    CrawlaAnchorSearchResponse,
    CrawlaHotelAnchorItem,
    CrawlaHotelOffer,
    CrawlaSearchAnchorItem,
)


class CrawlaApiError(RuntimeError):
    pass


class CrawlaClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self.settings = get_settings()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "CrawlaClient":
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

    def _base_url(self) -> str:
        base = self.settings.crawla_api_url.rstrip("/")
        if not base:
            raise CrawlaApiError("CRAWLA_API_URL not configured in backend/.env")
        return base

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = self.settings.crawla_api_key.strip()
        if api_key:
            headers["apikey"] = api_key
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True
        return self._client

    async def search_anchor(self, request: CrawlaAnchorRequest) -> CrawlaAnchorSearchResponse:
        payload = {
            "atg_hotel_ids": request.atg_hotel_ids,
            "checkin_date": request.check_in,
            "checkout_date": request.check_out,
            "adult_count": 2,
            "room_count": 1,
            "kids_count": 0,
            "currency": "SAR",
        }
        data = await self._post_json("/minPriceFlexible", payload)
        return CrawlaAnchorSearchResponse(
            data=[_normalize_search_item(item) for item in _as_list(data.get("data"))]
        )

    async def packages_anchor(self, request: CrawlaAnchorRequest) -> CrawlaAnchorPackagesResponse:
        payload = {
            "atg_hotel_ids": request.atg_hotel_ids,
            "checkin_date": request.check_in,
            "checkout_date": request.check_out,
            "adult_count": 2,
            "room_count": 1,
            "kids_count": 0,
            "currency": "SAR",
        }
        data = await self._post_json("/hotelPage", payload)
        return CrawlaAnchorPackagesResponse(
            hotels=[_normalize_hotel_item(item) for item in _as_list(data.get("hotels"))]
        )

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        response = await client.post(
            f"{self._base_url()}{path}",
            json=payload,
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise CrawlaApiError(
                f"Crawla API failed status={response.status_code} path={path} body={response.text}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise CrawlaApiError(f"Crawla API returned non-object payload for {path}")
        return data


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_search_item(item: Any) -> CrawlaSearchAnchorItem:
    if not isinstance(item, dict):
        return CrawlaSearchAnchorItem(atg_id="", min_price=None)
    return CrawlaSearchAnchorItem(
        atg_id=str(item.get("atg_id") or item.get("atgHotelId") or item.get("atg_hotel_id") or ""),
        min_price=_as_float(item.get("min_price")),
        total_amount=_as_float(item.get("total_amount")),
        room_name=_as_str(item.get("room_name") or item.get("roomName")),
        room_basis=_as_str(item.get("room_basis") or item.get("roomBasis")),
        base_amount=_as_float(item.get("base_amount")),
        tax_amount=_as_float(item.get("tax_amount")),
        currency=_as_str(item.get("currency")),
    )


def _normalize_hotel_item(item: Any) -> CrawlaHotelAnchorItem:
    if not isinstance(item, dict):
        return CrawlaHotelAnchorItem(atg_id="", data=[])

    offers = []
    for row in _as_list(item.get("data")):
        if isinstance(row, dict):
            offers.append(
                    CrawlaHotelOffer(
                        room_id=_as_str(row.get("room_id")) or "",
                        room_name=_as_str(row.get("room_name") or row.get("roomName")) or "",
                        total_amount=_as_float(row.get("total_amount")) or 0.0,
                        room_basis=_as_str(row.get("room_basis") or row.get("roomBasis")),
                        meal=_as_str(row.get("meal")),
                        refundability=_as_str(row.get("refundability")),
                        bed_type=_as_str(row.get("bed_type")),
                    )
                )

    return CrawlaHotelAnchorItem(
        atg_id=str(item.get("atg_id") or item.get("atgHotelId") or item.get("atg_hotel_id") or ""),
        min_price=_as_float(item.get("min_price")),
        status=_as_str(item.get("status")),
        data=offers,
    )


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
