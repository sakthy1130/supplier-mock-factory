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
            "currency": "USD",
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
            "currency": "USD",
        }
        data = await self._post_json("/hotelPage", payload)
        hotels = [_normalize_hotel_item(item) for item in _as_list(data.get("hotels"))]
        _filter_prepay_offers(hotels)
        return CrawlaAnchorPackagesResponse(hotels=hotels)

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
            bed_type = _as_str(row.get("bed_type"))
            offers.append(
                    CrawlaHotelOffer(
                        room_id=_as_str(row.get("room_id")) or "",
                        room_name=_compose_room_name(
                            _as_str(row.get("room_name") or row.get("roomName")),
                            bed_type,
                        ),
                        total_amount=_as_float(row.get("total_amount")) or 0.0,
                        room_basis=_as_str(row.get("room_basis") or row.get("roomBasis")),
                        meal=_as_str(row.get("meal")),
                        refundability=_as_str(row.get("refundability")),
                        bed_type=bed_type,
                        pay_at_property=_as_str(row.get("pay_at_property")),
                    )
                )

    return CrawlaHotelAnchorItem(
        atg_id=str(item.get("atg_id") or item.get("atgHotelId") or item.get("atg_hotel_id") or ""),
        min_price=_as_float(item.get("min_price")),
        status=_as_str(item.get("status")),
        data=offers,
    )


def _is_postpay(offer: CrawlaHotelOffer) -> bool:
    """Crawla marks pay-at-property (PostPay) offers with pay_at_property == 'Yes'."""
    return (offer.pay_at_property or "").strip().lower() == "yes"


def _filter_prepay_offers(hotels: list[CrawlaHotelAnchorItem]) -> None:
    """Keep only PrePay offers (pay_at_property != 'Yes') for the next process.

    HBS packages are PrePay, so a PostPay (pay-at-property) Crawla offer can never
    pair with HBS in PACKAGES_INITIATIVES. Drop PostPay offers; if *every* offer is
    PostPay, raise so the UI tells the user to pick different data.
    """
    all_offers = [offer for hotel in hotels for offer in hotel.data]
    if all_offers and all(_is_postpay(offer) for offer in all_offers):
        raise CrawlaApiError(
            "All Crawla packages are PostPay (pay-at-property) only. "
            "HBS is PrePay, so no package can pair for markup — try other hotel/dates."
        )
    for hotel in hotels:
        hotel.data = [offer for offer in hotel.data if not _is_postpay(offer)]


def _compose_room_name(room_name: Optional[str], bed_type: Optional[str]) -> str:
    """Crawla /hotelPage splits the name: room_name=" Double Room", bed_type="2 twin beds".

    The Crawla search/serp response the user compares against carries the full
    "Double Room 2 twin beds" in room_name, so rebuild it by appending bed_type
    (unless it is already present in the name).
    """
    name = (room_name or "").strip()
    bed = (bed_type or "").strip()
    if bed and bed.lower() not in name.lower():
        name = f"{name} {bed}".strip()
    return name


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
