"""Client for the connectivity core app search/package rerun flow."""

from __future__ import annotations

import asyncio
import uuid
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
        # Core blocks booking on dev/staging (E2002 "Booking url is blocked") unless
        # the request carries the test tenant. This is the same tenant the apiKey /
        # contract were provisioned under, so send it on every core call.
        tenant = getattr(self.settings, "tenant_id", "")
        if tenant:
            headers["x-tenant"] = tenant
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
        booking_selection: Optional[dict[str, Any]] = None,
    ) -> CrawlaRunScenarioResponse:
        """Drive the core flow. When ``booking_selection`` is provided (the
        scenario's selected package, e.g. {"price", "board", "room_name"}), the
        flow continues past packages into book → poll → getOrder and asserts the
        retrieved order matches the selected package."""
        trace: list[dict[str, str]] = []
        search_s_id = ""
        search_status = ""
        search_hotel_id = hotel_id
        package_p_id = ""
        package_status = ""
        error_message = None
        package_poll: dict[str, Any] = {}
        booking: dict[str, Any] = {}
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

            if booking_selection is not None:
                booking = await self._run_booking_flow(
                    api_key=api_key,
                    search_s_id=search_s_id,
                    package_p_id=package_p_id,
                    package_poll=package_poll,
                    hotel_id=search_hotel_id,
                    selection=booking_selection,
                    trace=trace,
                )
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
            booking_b_id=booking.get("b_id"),
            booking_status=booking.get("booking_status"),
            order_status=booking.get("order_status"),
            order_price=booking.get("order_price"),
            selected_package_id=booking.get("package_id"),
            booking_match=booking.get("match"),
            booking_message=booking.get("message"),
        )

    async def _run_booking_flow(
        self,
        *,
        api_key: str,
        search_s_id: str,
        package_p_id: str,
        package_poll: dict[str, Any],
        hotel_id: str,
        selection: dict[str, Any],
        trace: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Book the selected package and retrieve the order. Booking problems are
        captured into the returned dict (match=False) rather than aborting the
        whole run — search/package results still surface."""
        result: dict[str, Any] = {}
        try:
            package = _select_package(package_poll, selection)
            if package is None:
                result["match"] = False
                result["message"] = "No package found in the core /packages/poll response"
                return result

            package_id = _as_str(package.get("packageId"))
            result["package_id"] = package_id
            rooms = package.get("rooms") if isinstance(package.get("rooms"), list) else []
            lead_room_id = ""
            if rooms and isinstance(rooms[0], dict):
                lead_room_id = _as_str(rooms[0].get("roomId") or rooms[0].get("id"))
            # bookingPrice must equal packageRateInfo.total (core re-verifies it).
            # net_price is the pre-markup value that matches the UI-entered price.
            booked_total = _package_total(package)
            net_price = _package_net(package)

            passengers, lead_pax_id = _build_passengers(package)
            booking_payload = {
                "bookingRequest": {
                    "clientIp": "127.0.0.1",
                    "agentRemarks": "SMF booking-flow verification",
                    "specialRequest": "",
                    "bookingPrice": booked_total,
                    "hotelId": _as_int(hotel_id),
                    "internalReference": f"SMF{uuid.uuid4().hex[:8].upper()}",
                    "packages": [
                        {
                            "leadPaxId": lead_pax_id,
                            "leadPaxRoomId": lead_room_id,
                            "packageId": package_id,
                            "passengers": passengers,
                        }
                    ],
                    "paymentMethod": 0,
                    "serviceFee": None,
                },
                "sId": search_s_id,
                "pId": package_p_id,
            }
            booking_start = await self._post_json("/booking", booking_payload, api_key=api_key, trace=trace)
            b_id = _as_str(booking_start.get("bId") or booking_start.get("bid"))
            result["b_id"] = b_id
            if not b_id:
                result["match"] = False
                result["message"] = "Core booking response missing bId"
                return result

            booking_poll = await self._poll_booking(b_id, api_key=api_key, trace=trace)
            result["booking_status"] = _extract_first_value(booking_poll, "pollingStatus") or "UNKNOWN"

            segment_id = _extract_segment_id(booking_poll)
            order_payload = {
                "sId": search_s_id,
                "bId": b_id,
                "orderRequest": {"segmentId": segment_id},
            }
            order = await self._post_json("/booking/get-order", order_payload, api_key=api_key, trace=trace)
            result["order_status"] = _extract_order_status(order)
            order_price = _extract_order_price(order)
            result["order_price"] = order_price

            # Markup-aware verdict: compare the order total to the booked package's
            # total (net + markup), NOT the raw UI net — otherwise BR markup always
            # looks like a mismatch.
            statuses_ok = (
                result["booking_status"] == "COMPLETED_SUCCESSFULLY"
                and result.get("order_status") == "OK"
            )
            price_ok = (
                booked_total is not None
                and order_price is not None
                and abs(float(order_price) - float(booked_total)) < 0.01
            )
            result["match"] = bool(statuses_ok and price_ok)
            result["message"] = _booking_message(
                statuses_ok=statuses_ok,
                price_ok=price_ok,
                net_price=net_price,
                booked_total=booked_total,
                order_price=order_price,
                order_status=result.get("order_status"),
            )
        except CoreAppError as exc:
            result["match"] = False
            result["message"] = str(exc)
        return result

    async def _poll_booking(
        self,
        b_id: str,
        *,
        api_key: str,
        trace: list[dict[str, str]],
        attempts: int = 16,
        delay_seconds: float = 2.0,
    ) -> dict[str, Any]:
        """Poll /booking/poll/{bId} to the core contract: success is
        COMPLETED_SUCCESSFULLY with totalResults > 0; COMPLETED_WITH_FAILURE (or
        any other terminal status) surfaces errors[0].errorCode."""
        path = f"/booking/poll/{b_id}"
        last: Optional[dict[str, Any]] = None
        for attempt in range(1, attempts + 1):
            data = await self._request_json(path, method="GET", api_key=api_key)
            if isinstance(data, dict):
                last = data
                status = _extract_first_value(data, "pollingStatus")
                total_results = _as_float(_first_value_raw(data, "totalResults")) or 0
                trace.append(
                    {
                        "step": "booking",
                        "method": "GET",
                        "path": path,
                        "attempt": str(attempt),
                        "status": status or "",
                        "http_status": "200",
                    }
                )
                if status == "COMPLETED_SUCCESSFULLY" and total_results > 0:
                    return data
                if status and status != "IN_PROGRESS":
                    error_code = _extract_first_value(data, "errorCode")
                    detail = f" errorCode={error_code}" if error_code else ""
                    raise CoreAppError(
                        f"Core booking failed: pollingStatus={status} totalResults={int(total_results)}{detail}"
                    )
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)
        raise CoreAppError(
            f"Core booking poll timed out for {path}; last status="
            f"{_extract_first_value(last or {}, 'pollingStatus')!r}"
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


def _core_packages(package_poll: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the package list from a /packages/poll response
    (packagesResult.packages), tolerating a few shape variants."""
    result = package_poll.get("packagesResult")
    if isinstance(result, dict):
        packages = result.get("packages")
        if isinstance(packages, list):
            return [p for p in packages if isinstance(p, dict)]
    packages = package_poll.get("packages")
    if isinstance(packages, list):
        return [p for p in packages if isinstance(p, dict)]
    return []


def _package_total(package: dict[str, Any]) -> Optional[float]:
    """Final package price (net + markup) — packageRateInfo.total."""
    rate_info = package.get("packageRateInfo")
    if isinstance(rate_info, dict):
        for key in ("total", "totalPrice", "amount"):
            value = _as_float(rate_info.get(key))
            if value is not None:
                return value
    for key in ("total", "totalPrice", "price"):
        value = _as_float(package.get(key))
        if value is not None:
            return value
    return None


def _package_net(package: dict[str, Any]) -> Optional[float]:
    """Pre-markup net price — packageRateInfo.netPrice (matches the UI price)."""
    rate_info = package.get("packageRateInfo")
    if isinstance(rate_info, dict):
        for key in ("netPrice", "net"):
            value = _as_float(rate_info.get(key))
            if value is not None:
                return value
    return None


def _package_room_basis(package: dict[str, Any]) -> list[str]:
    rooms = package.get("rooms")
    basis: list[str] = []
    if isinstance(rooms, list):
        for room in rooms:
            if isinstance(room, dict):
                code = _as_str(room.get("roomBasis"))
                if code:
                    basis.append(code.upper())
    return basis


def _package_room_names(package: dict[str, Any]) -> list[str]:
    rooms = package.get("rooms")
    names: list[str] = []
    if isinstance(rooms, list):
        for room in rooms:
            if not isinstance(room, dict):
                continue
            name = room.get("roomName")
            if isinstance(name, dict):
                name = name.get("en") or name.get("ar")
            name = _as_str(name) or _as_str(room.get("originalRoomName"))
            if name:
                names.append(name)
    return names


def _select_package(package_poll: dict[str, Any], selection: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Pick the core package matching the UI selection, using markup-invariant
    signals first (board + room name), then the net price, then the first
    package as a last resort."""
    packages = _core_packages(package_poll)
    if not packages:
        return None
    if len(packages) == 1:
        return packages[0]

    board = _as_str(selection.get("board")).upper()
    room_name = _as_str(selection.get("room_name")).strip().lower()

    # 1) board + room name (markup-invariant)
    if board or room_name:
        for package in packages:
            basis = _package_room_basis(package)
            names = [n.strip().lower() for n in _package_room_names(package)]
            board_ok = (not board) or (board in basis)
            name_ok = (not room_name) or (room_name in names)
            if board_ok and name_ok and (board or room_name):
                return package

    # 2) net price (pre-markup; matches the UI-entered price)
    expected = _as_float(selection.get("price"))
    if expected is not None:
        best: Optional[dict[str, Any]] = None
        best_delta = float("inf")
        for package in packages:
            net = _package_net(package)
            candidate = net if net is not None else _package_total(package)
            if candidate is None:
                continue
            delta = abs(candidate - expected)
            if delta < best_delta:
                best_delta = delta
                best = package
        if best is not None:
            return best

    # 3) fall back to the first package
    return packages[0]


def _build_passengers(package: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Build occupancy-correct passengers for the booking request and return
    (passengers, lead_pax_id). The core search runs 2 adults, so each room needs
    that many adult passengers (plus one child per kid age); the first adult's
    paxId is reused as leadPaxId. Shape mirrors qaBackend_Enigma getPackagesObj."""
    rooms = package.get("rooms") if isinstance(package.get("rooms"), list) else []
    if not rooms:
        rooms = [{}]

    passengers: list[dict[str, Any]] = []
    lead_pax_id = ""
    for room in rooms:
        room = room if isinstance(room, dict) else {}
        room_id = _as_str(room.get("roomId") or room.get("id"))
        adults = int(_as_float(room.get("numberOfAdults")) or 2)
        kids_ages = room.get("kidsAges") if isinstance(room.get("kidsAges"), list) else []
        for _ in range(max(adults, 1)):
            pax_id = str(uuid.uuid4())
            if not lead_pax_id:
                lead_pax_id = pax_id
            passengers.append(_passenger(room_id, pax_id, age=None))
        for age in kids_ages:
            passengers.append(_passenger(room_id, str(uuid.uuid4()), age=_as_float(age)))

    if not lead_pax_id:
        lead_pax_id = str(uuid.uuid4())
        passengers.append(_passenger("", lead_pax_id, age=None))
    return passengers, lead_pax_id


def _passenger(room_id: str, pax_id: str, *, age: Optional[float]) -> dict[str, Any]:
    is_child = age is not None
    person: dict[str, Any] = {
        "email": "Test@domain.com",
        "telephone": "+1 786 581 41 46",
        "name": {
            "namePrefix": "Miss." if is_child else "Mr.",
            "givenName": "QA",
            "surname": "Smf",
            "middleName": "T",
        },
        "type": 1 if is_child else 0,
    }
    if is_child:
        person["age"] = int(age)
    return {
        "address": {
            "addressLine": "address line",
            "cityName": "city",
            "countryName": {"code": "US"},
            "postalCode": "123456",
        },
        "roomId": room_id,
        "paxId": pax_id,
        "email": "Email@address.com",
        "personDetails": person,
    }


def _booking_message(
    *,
    statuses_ok: bool,
    price_ok: bool,
    net_price: Optional[float],
    booked_total: Optional[float],
    order_price: Optional[float],
    order_status: Optional[str],
) -> str:
    def fmt(value: Optional[float]) -> str:
        return f"{value:.2f}" if value is not None else "n/a"

    detail = (
        f"net {fmt(net_price)}, +markup total {fmt(booked_total)}, order {fmt(order_price)}"
    )
    if statuses_ok and price_ok:
        return f"Booking created (order {order_status}) — {detail} (match)"
    if statuses_ok and not price_ok:
        return f"Order {order_status} but price differs — {detail}"
    return f"Booking not successful (order status {order_status}) — {detail}"


def _extract_segment_id(booking_poll: dict[str, Any]) -> str:
    booking_result = booking_poll.get("bookingResult")
    if isinstance(booking_result, dict):
        results = booking_result.get("bookingResults")
        if isinstance(results, list):
            for entry in results:
                if isinstance(entry, dict):
                    seg = _as_str(entry.get("segmentId"))
                    if seg:
                        return seg
    return _extract_first_value(booking_poll, "segmentId")


def _extract_order_status(order: dict[str, Any]) -> str:
    results = order.get("orderResults")
    if isinstance(results, dict):
        details = results.get("orderDetails")
        if isinstance(details, dict):
            status = _as_str(details.get("orderStatus"))
            if status:
                return status
    return _extract_first_value(order, "orderStatus")


def _extract_order_price(order: dict[str, Any]) -> Optional[float]:
    results = order.get("orderResults")
    if isinstance(results, dict):
        details = results.get("orderDetails")
        if isinstance(details, dict):
            segments = details.get("segments")
            seg = None
            if isinstance(segments, list) and segments:
                seg = segments[0]
            elif isinstance(segments, dict):
                seg = segments
            if isinstance(seg, dict):
                price = seg.get("price")
                if isinstance(price, dict):
                    value = _parse_price_scalar(price.get("total"))
                    if value is not None:
                        return value
    return None


def _parse_price_scalar(value: Any) -> Optional[float]:
    """Parse a price that core may return as a number, a plain string, an
    "array-in-string" like "[222.0]", or a single-element list."""
    if isinstance(value, list):
        for item in value:
            parsed = _parse_price_scalar(item)
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, str):
        cleaned = value.strip().strip("[]").split(",")[0].strip()
        return _as_float(cleaned)
    return _as_float(value)


def _extract_first_value(node: Any, key: str) -> str:
    if isinstance(node, dict):
        if key in node:
            value = _as_str(node.get(key))
            if value:
                return value
        for value in node.values():
            found = _extract_first_value(value, key)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _extract_first_value(item, key)
            if found:
                return found
    return ""


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Any:
    """Best-effort int for hotelId; leaves the original value if non-numeric."""
    parsed = _as_float(value)
    if parsed is None:
        return value
    return int(parsed)


def _first_value_raw(node: Any, key: str) -> Any:
    """Like _extract_first_value but returns the raw (non-stringified) value."""
    if isinstance(node, dict):
        if key in node and node.get(key) is not None:
            return node.get(key)
        for value in node.values():
            found = _first_value_raw(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _first_value_raw(item, key)
            if found is not None:
                return found
    return None


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
