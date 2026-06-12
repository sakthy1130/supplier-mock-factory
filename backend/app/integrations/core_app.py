"""Client for the connectivity core app search/package rerun flow."""

from __future__ import annotations

import asyncio
from typing import Any
from typing import Optional

import httpx

from app.config import get_settings
from app.models.crawla import CrawlaRunScenarioResponse


class CoreAppError(RuntimeError):
    pass


class CoreAppClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self.settings = get_settings()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "CoreAppClient":
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
        base = self.settings.core_app_url.rstrip("/")
        if not base:
            raise CoreAppError("CORE_APP_URL not configured in backend/.env")
        return base

    def _headers(self, api_key: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True
        return self._client

    async def run_search_and_packages(
        self,
        *,
        api_key: str,
        check_in: str,
        check_out: str,
        hotel_id: str,
    ) -> CrawlaRunScenarioResponse:
        trace: list[dict[str, str]] = []
        search_s_id = ""
        search_status = ""
        search_hotel_id = hotel_id
        package_p_id = ""
        package_status = ""
        error_message = None
        try:
            search_payload = {
                "searchRequest": {
                    "currency": "SAR",
                    "nationality": "SA",
                    "residency": "SA",
                    "checkIn": check_in,
                    "checkOut": check_out,
                    "roomsInfo": [
                        {
                            "adultsCount": 2,
                            "kidsAges": [],
                        }
                    ],
                    "excludeSupplierIds": None,
                    "ipCountryCode": "SA",
                    "geoLocation": None,
                    "hotelIds": [hotel_id],
                }
            }
            search_start = await self._post_json("/search", search_payload, api_key=api_key, trace=trace)
            search_s_id = _as_str(search_start.get("sId") or search_start.get("sid"))
            if not search_s_id:
                raise CoreAppError("Core search response missing sId")

            search_poll = await self._poll_until_completed(
                f"/search/poll/{search_s_id}",
                status_keys=(
                    "pollingStatus",
                    "searchStatus",
                    "search_status",
                    "status",
                    "state",
                    "taskStatus",
                ),
                api_key=api_key,
                trace=trace,
            )
            search_status = _extract_status(
                search_poll,
                (
                    "pollingStatus",
                    "searchStatus",
                    "search_status",
                    "status",
                    "state",
                    "taskStatus",
                ),
            ) or "UNKNOWN"
            search_hotel_id = _extract_search_hotel_id(search_poll, hotel_id)

            packages_payload = {
                "sId": search_s_id,
                "packagesRequest": {
                    "hotelId": search_hotel_id,
                },
            }
            packages_start = await self._post_json("/packages", packages_payload, api_key=api_key, trace=trace)
            package_p_id = _as_str(packages_start.get("pId") or packages_start.get("pid"))
            if not package_p_id:
                raise CoreAppError("Core packages response missing pId")

            package_poll = await self._poll_until_completed(
                f"/packages/poll/{package_p_id}",
                status_keys=(
                    "pollingStatus",
                    "packageStatus",
                    "package_status",
                    "status",
                    "state",
                    "taskStatus",
                ),
                api_key=api_key,
                trace=trace,
            )
            package_status = _extract_status(
                package_poll,
                (
                    "pollingStatus",
                    "packageStatus",
                    "package_status",
                    "status",
                    "state",
                    "taskStatus",
                ),
            ) or "UNKNOWN"
        except CoreAppError as exc:
            error_message = str(exc)

        return CrawlaRunScenarioResponse(
            scenario_id="",
            search_s_id=search_s_id,
            search_status=search_status,
            search_hotel_id=search_hotel_id,
            package_p_id=package_p_id,
            package_status=package_status,
            error_message=error_message,
            logs=trace,
        )

    async def _poll_until_completed(
        self,
        path: str,
        *,
        status_keys: tuple[str, ...],
        api_key: str,
        trace: list[dict[str, str]],
        use_post: bool = False,
        attempts: int = 16,
        delay_seconds: float = 2.0,
    ) -> dict[str, Any]:
        last: Optional[dict[str, Any]] = None
        for attempt in range(1, attempts + 1):
            data = await self._request_json(
                path,
                method="POST" if use_post else "GET",
                api_key=api_key,
            )
            if isinstance(data, dict):
                last = data
                status = _extract_status(data, status_keys)
                trace.append(
                    {
                        "step": path.rsplit("/", 1)[0].replace("/poll", "").lstrip("/"),
                        "method": "POST" if use_post else "GET",
                        "path": path,
                        "attempt": str(attempt),
                        "status": status or "",
                        "http_status": "200",
                    }
                )
                if status == "COMPLETED_SUCCESSFULLY":
                    return data
                if status and status not in {"PENDING", "PROCESSING", "IN_PROGRESS", "QUEUED"}:
                    raise CoreAppError(f"Core polling failed at {path}: {status}")
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)
        if last is None:
            raise CoreAppError(f"Core polling returned no data for {path}")
        raise CoreAppError(
            f"Core polling timed out at {path} after {attempts} attempts; last={_extract_status(last, status_keys)!r}"
        )

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        api_key: str,
        trace: list[dict[str, str]],
    ) -> dict[str, Any]:
        data = await self._request_json(path, method="POST", payload=payload, api_key=api_key)
        if not isinstance(data, dict):
            raise CoreAppError(f"Core API returned non-object payload for {path}")
        trace.append(
            {
                "step": path.strip("/"),
                "method": "POST",
                "path": path,
                "attempt": "1",
                "status": _extract_status(
                    data,
                    ("pollingStatus", "searchStatus", "packageStatus", "status", "state", "taskStatus"),
                ),
                "http_status": "200",
            }
        )
        return data

    async def _request_json(
        self,
        path: str,
        *,
        method: str,
        api_key: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> Any:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "headers": self._headers(api_key),
        }
        if payload is not None:
            kwargs["json"] = payload
        response = await client.request(method, f"{self._base_url()}{path}", **kwargs)
        if response.status_code != 200:
            raise CoreAppError(
                f"Core API failed status={response.status_code} path={path} body={response.text}"
            )
        return response.json()


def _extract_search_hotel_id(payload: dict[str, Any], fallback: str) -> str:
    results = payload.get("searchResults")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            hotel_id = _as_str(first.get("hotelId") or first.get("hotel_id"))
            if hotel_id:
                return hotel_id
    return fallback


def _extract_status(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    value = _extract_status_from_node(payload, keys)
    if value:
        return value
    return ""


def _extract_status_from_node(node: Any, keys: tuple[str, ...]) -> str:
    if isinstance(node, dict):
        for key in keys:
            value = _as_str(node.get(key))
            if value:
                return value
        for value in node.values():
            nested = _extract_status_from_node(value, keys)
            if nested:
                return nested
    elif isinstance(node, list):
        for item in node:
            nested = _extract_status_from_node(item, keys)
            if nested:
                return nested
    return ""


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text
