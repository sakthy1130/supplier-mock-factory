"""ATG ↔ supplier hotel id mapping via hotels-integration-mapping-service."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class HotelMappingError(RuntimeError):
    pass


class HotelMappingClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "HotelMappingClient":
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
        base = self.settings.mapping_service_url.rstrip("/")
        if not base:
            raise HotelMappingError("MAPPING_SERVICE_URL not configured in backend/.env")
        return base

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        api_key = self.settings.mapping_api_key.strip()
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True
        return self._client

    async def resolve_supplier_hotel_id(
        self,
        atg_hotel_id: str,
        supplier_code: str,
    ) -> str:
        """
        GET /v2/supplier/{supplierCode}/{atgHotelId}

        Example: /v2/supplier/HBS/1446194 -> supplierHotelId 156652
        """
        atg_id = atg_hotel_id.strip()
        code = supplier_code.strip().upper()
        if not atg_id:
            raise HotelMappingError("atg_hotel_id is required")
        if not code:
            raise HotelMappingError("supplier_code is required")

        url = f"{self._base_url()}/v2/supplier/{code}/{atg_id}"
        client = self._get_client()
        try:
            response = await client.get(url, headers=self._headers())
        except httpx.ConnectError as exc:
            raise HotelMappingError(
                f"Cannot reach mapping service at {self._base_url()} — "
                f"check MAPPING_SERVICE_URL in backend/.env and ensure you are on the staging VPN. "
                f"Detail: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise HotelMappingError(
                f"Mapping service timed out (supplier={code} atg={atg_id}): {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise HotelMappingError(
                f"Mapping service HTTP error (supplier={code} atg={atg_id}): {exc}"
            ) from exc

        if response.status_code != 200:
            raise HotelMappingError(
                f"Mapping API failed status={response.status_code} "
                f"supplier={code} atg={atg_id} body={response.text}"
            )

        return _parse_single_supplier_response(response.json(), code, atg_id)

    async def resolve_supplier_hotel_ids(
        self,
        atg_hotel_id: str,
        supplier_codes: list[str],
    ) -> dict[str, str]:
        """Resolve ATG id to supplier hotel id for each supplier code."""
        if not supplier_codes:
            raise HotelMappingError("At least one supplier code required")

        resolved: dict[str, str] = {}
        for code in supplier_codes:
            resolved[code] = await self.resolve_supplier_hotel_id(atg_hotel_id, code)
        return resolved


def _parse_single_supplier_response(
    payload: dict[str, Any],
    supplier_code: str,
    atg_hotel_id: str,
) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        raise HotelMappingError(
            f"Mapping API errors for {supplier_code}: {errors}"
        )

    status_code = payload.get("statusCode")
    if status_code is not None and int(status_code) != 200:
        raise HotelMappingError(
            f"Mapping API statusCode={status_code} for {supplier_code} ATG {atg_hotel_id}"
        )

    response_obj = payload.get("response")
    if not isinstance(response_obj, dict):
        raise HotelMappingError(
            f"Mapping API response missing 'response' for {supplier_code}"
        )

    supplier_hotel_id = response_obj.get("supplierHotelId")
    if supplier_hotel_id is None or not str(supplier_hotel_id).strip():
        raise HotelMappingError(
            f"No supplierHotelId for {supplier_code} ATG {atg_hotel_id}"
        )

    resp_atg = str(response_obj.get("atgHotelId", "")).strip()
    if resp_atg and resp_atg != str(atg_hotel_id).strip():
        logger.warning(
            "Mapping ATG mismatch requested=%s response=%s supplier=%s",
            atg_hotel_id,
            resp_atg,
            supplier_code,
        )

    resp_code = str(response_obj.get("supplierCode", "")).strip().upper()
    if resp_code and resp_code != supplier_code.upper():
        logger.warning(
            "Mapping supplier mismatch requested=%s response=%s",
            supplier_code,
            resp_code,
        )

    return str(supplier_hotel_id).strip()
