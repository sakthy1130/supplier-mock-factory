"""HBS supplier plugin. Port SupplierRankingHbsJsonUtils."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from app.core.cancel_policy import PENALTY_ALWAYS_FROM, format_cancel_from, free_cancel_deadline
from app.models.scenario import PackageSpec
from app.plugins.base import SupplierMockPlugin
from app.plugins.room_names import apply_hbs_room_names, normalized_room_basis, normalized_room_names
from app.plugins.supplier_currency import apply_hbs_supplier_currency
from app.plugins.json_utils import (
    collect_field_values,
    deep_copy,
    replace_in_json_strings,
    update_fields_recursive,
)

LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]


def _compact_date(value: str) -> str:
    return value.replace("-", "")


def _update_rate_key_dates(rate_key: str, check_in: str, check_out: str) -> str:
    parts = rate_key.split("|")
    if len(parts) >= 2:
        parts[0] = _compact_date(check_in)
        parts[1] = _compact_date(check_out)
    return "|".join(parts)


def _with_unique_rate_key_suffix(rate_key: str, index: int) -> str:
    return f"{rate_key}~SMF{index + 1}"


def _rewrite_rate_key_hotel_id(rate_key: str, new_code: Any) -> str:
    """Rewrite the hotel-code field in an HBS rateKey to the scenario's resolved
    supplier hotel id. Format: checkIn|checkOut|W|<dest>|<hotelCode>|<roomCode>|…
    (the 5th pipe field is the hotel code). Leaves the key unchanged if the shape
    doesn't match, so a non-standard rateKey is never corrupted."""
    if not isinstance(rate_key, str):
        return rate_key
    parts = rate_key.split("|")
    if len(parts) > 4 and parts[4].isdigit():
        parts[4] = str(new_code)
        return "|".join(parts)
    return rate_key


class HbsMockPlugin(SupplierMockPlugin):
    code = "HBS"

    def matches_adapter_source(self, source: str) -> bool:
        """Match e.g. hotel-connectivity-hbs-adapter."""
        s = source.lower()
        return "hotel" in s and "hbs" in s and "adapter" in s

    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        result = deep_copy(expectation)

        def update_check_in(value: Any) -> Any:
            return check_in

        def update_check_out(value: Any) -> Any:
            return check_out

        def update_rate_key(value: Any) -> Any:
            if isinstance(value, str) and "|" in value:
                return _update_rate_key_dates(value, check_in, check_out)
            return value

        update_fields_recursive(
            result,
            {
                "checkIn": update_check_in,
                "checkOut": update_check_out,
                "rateKey": update_rate_key,
            },
        )

        cp_date = (datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        replace_in_json_strings(result, [(check_in, check_in)])
        # Shift embedded cancellation-policy sample dates toward new check-in window.
        for old_cp in collect_field_values(result, "from"):
            if isinstance(old_cp, str) and "T" in old_cp:
                replace_in_json_strings(result, [(old_cp.split("T")[0], cp_date)])

        return result

    def mutate_packages(
        self,
        expectation: dict,
        spec: PackageSpec,
        hotel_id: str,
        check_in: str,
        check_out: str,
        log_type: str,
    ) -> dict:
        if log_type == "Search":
            return self._mutate_search_hotel(expectation, hotel_id, spec)

        result = deep_copy(expectation)
        refundable = _normalized_refundable(spec)
        prices = _normalized_prices(spec)

        request_json = (
            result.get("httpRequest", {}).get("body", {}).get("json")
            if isinstance(result.get("httpRequest", {}).get("body"), dict)
            else None
        )
        if isinstance(request_json, dict) and "hotels" in request_json:
            hotels = request_json.setdefault("hotels", {})
            if isinstance(hotels, dict):
                hotels["hotel"] = [int(hotel_id)]

        body = result.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return result

        if log_type == "GetOrder":
            self._force_confirmed_get_order(result)

        hotels_wrapper = body.get("hotels")
        if not isinstance(hotels_wrapper, dict):
            return result

        hotel_list = hotels_wrapper.get("hotels")
        if not isinstance(hotel_list, list) or not hotel_list:
            return result

        hotel = hotel_list[0]
        if isinstance(hotel, dict):
            hotel["code"] = int(hotel_id)

        rooms = hotel.get("rooms") if isinstance(hotel, dict) else None
        if not isinstance(rooms, list) or not rooms:
            return result

        room = rooms[0]
        rates = room.get("rates") if isinstance(room, dict) else None
        if not isinstance(rates, list) or not rates:
            return result

        template_rate = deep_copy(rates[0])
        room_basis_list = normalized_room_basis(spec)
        new_rates = []
        for index in range(spec.count):
            source_rate = rates[index % len(rates)]
            original_basis = source_rate.get("boardCode") if isinstance(source_rate, dict) else None
            rate = deep_copy(source_rate)
            price = prices[index]
            is_refundable = refundable[index]
            basis = room_basis_list[index]
            rate["net"] = str(price)
            rate["boardCode"] = basis
            rate["boardName"] = _board_name(basis)
            _apply_hbs_rate_refundability(rate, price, is_refundable, check_in, check_out)
            if isinstance(rate.get("rateKey"), str):
                # The rateKey embeds the board token from whichever raw template rate
                # we cycled to (rates may not all share the same original board code) —
                # replace THAT token, not a hardcoded "RO", or the rateKey silently
                # keeps stale board info out of sync with the boardCode field above.
                token = original_basis if isinstance(original_basis, str) and original_basis else "RO"
                rate["rateKey"] = rate["rateKey"].replace(f" {token}|", f" {basis}|")
                if index >= len(rates):
                    rate["rateKey"] = _with_unique_rate_key_suffix(rate["rateKey"], index)
                # The rateKey embeds the hotel code (…|<dest>|<hotelCode>|<roomCode>|…);
                # the template's is baked to the default hotel, so rewrite it to the
                # scenario's resolved supplier hotel id or checkrate/booking references
                # the wrong hotel.
                rate["rateKey"] = _rewrite_rate_key_hotel_id(rate["rateKey"], hotel_id)
            new_rates.append(rate)

        room_names = normalized_room_names(spec)
        if len(set(room_names)) == 1:
            room["rates"] = new_rates
            if isinstance(hotel, dict):
                hotel["rooms"] = [room]
        else:
            new_rooms = []
            for index, rate in enumerate(new_rates):
                room_copy = deep_copy(room)
                room_copy["rates"] = [rate]
                new_rooms.append(room_copy)
            if isinstance(hotel, dict):
                hotel["rooms"] = new_rooms

        if prices:
            primary_price = str(prices[0])
            serialized = json.dumps(result)
            old_net = str(template_rate.get("net", ""))
            if old_net:
                serialized = serialized.replace(old_net, primary_price)
            result = json.loads(serialized)

        apply_hbs_supplier_currency(result, spec.supplier_currency)
        return result

    def _mutate_search_hotel(self, expectation: dict, hotel_id: str, spec: PackageSpec) -> dict:
        """Search mock returns exactly one hotel — the scenario hotel_id."""
        result = deep_copy(expectation)
        hotel_code = int(hotel_id)

        request_json = (
            result.get("httpRequest", {}).get("body", {}).get("json")
            if isinstance(result.get("httpRequest", {}).get("body"), dict)
            else None
        )
        if isinstance(request_json, dict):
            hotels = request_json.setdefault("hotels", {})
            if isinstance(hotels, dict):
                hotels["hotel"] = [hotel_code]

        body = result.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return result

        hotels_wrapper = body.get("hotels")
        if not isinstance(hotels_wrapper, dict):
            return result

        hotel_list = hotels_wrapper.get("hotels")
        if not isinstance(hotel_list, list) or not hotel_list:
            return result

        template_hotel = None
        template_old_code = None
        for entry in hotel_list:
            if isinstance(entry, dict) and entry.get("code") == hotel_code:
                template_hotel = deep_copy(entry)
                template_old_code = hotel_code
                break
        if template_hotel is None:
            template_hotel = deep_copy(hotel_list[0])
            template_old_code = template_hotel.get("code")

        template_hotel["code"] = hotel_code
        _rewrite_hotel_code_in_rates(template_hotel, hotel_code, template_old_code)

        hotels_wrapper["hotels"] = [template_hotel]
        if "total" in hotels_wrapper:
            hotels_wrapper["total"] = 1

        apply_hbs_supplier_currency(result, spec.supplier_currency)
        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        room_names = normalized_room_names(spec)
        if room_names:
            self._apply_room_names(expectations_by_type, room_names)

        self._link_booking_flow(expectations_by_type, spec)

        packages = expectations_by_type.get("Packages")
        prebook = expectations_by_type.get("PreBooking")
        if not packages or not prebook:
            return

        pkg_hotels = (
            packages.get("httpResponse", {})
            .get("body", {})
            .get("hotels", {})
            .get("hotels", [])
        )
        if not isinstance(pkg_hotels, list) or not pkg_hotels:
            return
        pkg_rooms = pkg_hotels[0].get("rooms") if isinstance(pkg_hotels[0], dict) else None
        if not isinstance(pkg_rooms, list) or not pkg_rooms:
            return
        pkg_rates = []
        for pkg_room in pkg_rooms:
            if not isinstance(pkg_room, dict):
                continue
            room_rates = pkg_room.get("rates")
            if isinstance(room_rates, list):
                pkg_rates.extend(room_rates)
        if not pkg_rates:
            return

        # Link PreBooking to the SELECTED package (not always index 0), so the
        # prebooking rate/CP matches the package that actually gets booked.
        idx = spec.booking_package_index
        if idx is not None and 0 <= idx < len(pkg_rates):
            primary_rate = pkg_rates[idx]
        else:
            primary_rate = pkg_rates[0]
        primary_rate_key = primary_rate.get("rateKey")
        primary_net = str(primary_rate.get("net", ""))
        primary_cps = primary_rate.get("cancellationPolicies")
        if not primary_rate_key:
            return

        request_body = prebook.get("httpRequest", {}).get("body", {})
        if isinstance(request_body, dict):
            payload = request_body.get("json")
            if isinstance(payload, dict):
                rooms = payload.get("rooms")
                if isinstance(rooms, list):
                    for room in rooms:
                        if isinstance(room, dict):
                            room["rateKey"] = primary_rate_key

        resp_body = prebook.get("httpResponse", {}).get("body")
        if not isinstance(resp_body, dict):
            return
        hotel = resp_body.get("hotel")
        if not isinstance(hotel, dict):
            return
        prebook_rooms = hotel.get("rooms")
        if not isinstance(prebook_rooms, list) or not prebook_rooms:
            return
        prebook_rates = prebook_rooms[0].get("rates") if isinstance(prebook_rooms[0], dict) else None
        if not isinstance(prebook_rates, list) or not prebook_rates:
            return

        template_old_net = str(prebook_rates[0].get("net", ""))
        for rate in prebook_rates:
            if not isinstance(rate, dict):
                continue
            rate["rateKey"] = primary_rate_key
            if primary_net:
                rate["net"] = primary_net
            if primary_rate.get("boardCode"):
                rate["boardCode"] = primary_rate["boardCode"]
                rate["boardName"] = _board_name(primary_rate["boardCode"])
            if primary_rate.get("rateClass"):
                rate["rateClass"] = primary_rate["rateClass"]
            # Copy the selected package's cancellation policy verbatim so the HBS
            # adapter's prebooking-vs-packages CP check sees zero drift. The
            # contract sets prebookingMaximumCPChangePercentage=0, so ANY
            # difference in amount/from is rejected as E3021.4.
            if isinstance(primary_cps, list):
                rate["cancellationPolicies"] = deep_copy(primary_cps)

        if template_old_net and primary_net and template_old_net != primary_net:
            serialized = json.dumps(prebook)
            serialized = serialized.replace(template_old_net, primary_net)
            synced = json.loads(serialized)
            prebook.clear()
            prebook.update(synced)

        search = expectations_by_type.get("Search")
        if not isinstance(search, dict):
            return
        search_body = search.get("httpResponse", {}).get("body")
        if not isinstance(search_body, dict):
            return
        search_hotels = search_body.get("hotels", {}).get("hotels")
        if not isinstance(search_hotels, list) or not search_hotels:
            return
        search_rooms = search_hotels[0].get("rooms") if isinstance(search_hotels[0], dict) else None
        if not isinstance(search_rooms, list) or not search_rooms:
            return
        search_hotels[0]["rooms"] = deep_copy(pkg_rooms)

    def _link_booking_flow(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        """Sync the selected package's rate into Booking/GetOrder/CancelOrder.

        Without this the booking-flow mocks ship their static template rate, so a
        booking retrieved via the core service never matches the package the user
        picked in search. Booking + GetOrder are forced to CONFIRMED with the
        selected net price; CancelOrder keeps its cancelled (net 0.00) semantics
        but still reflects the selected board/room/rateClass.
        """
        idx = spec.booking_package_index
        if idx is None:
            return
        packages = expectations_by_type.get("Packages")
        if not isinstance(packages, dict):
            return
        pkg_rates = _hbs_package_rates(packages)
        if not pkg_rates or idx >= len(pkg_rates):
            return
        sel = pkg_rates[idx]
        if not isinstance(sel, dict):
            return

        room_names = normalized_room_names(spec)
        if idx < len(room_names):
            room_name = room_names[idx]
        elif room_names:
            room_name = room_names[0]
        else:
            room_name = None

        net = str(sel.get("net", "")) or None
        board = sel.get("boardCode")
        rate_class = sel.get("rateClass")
        cancellation_policies = sel.get("cancellationPolicies")

        for log_type in ("Booking", "GetOrder", "CancelOrder"):
            expectation = expectations_by_type.get(log_type)
            if not isinstance(expectation, dict):
                continue
            confirmed = log_type in ("Booking", "GetOrder")
            if log_type == "GetOrder":
                self._force_confirmed_get_order(expectation)
            self._apply_hbs_booking_rate(
                expectation, net, board, rate_class, room_name, cancellation_policies, confirmed
            )

    @staticmethod
    def _apply_hbs_booking_rate(
        expectation: dict,
        net: str | None,
        board: Any,
        rate_class: Any,
        room_name: str | None,
        cancellation_policies: Any,
        confirmed: bool,
    ) -> None:
        booking = expectation.get("httpResponse", {}).get("body", {}).get("booking")
        if not isinstance(booking, dict):
            return
        hotel = booking.get("hotel")
        if not isinstance(hotel, dict):
            return
        rooms = hotel.get("rooms")
        if isinstance(rooms, list) and rooms and isinstance(rooms[0], dict):
            room = rooms[0]
            if room_name:
                room["name"] = room_name
            rates = room.get("rates")
            if isinstance(rates, list) and rates and isinstance(rates[0], dict):
                rate = rates[0]
                if isinstance(board, str) and board:
                    rate["boardCode"] = board
                    rate["boardName"] = _board_name(board)
                if isinstance(rate_class, str) and rate_class:
                    rate["rateClass"] = rate_class
                # Keep the booking-flow CP identical to the selected package's CP
                # so no downstream CP comparison drifts.
                if isinstance(cancellation_policies, list):
                    rate["cancellationPolicies"] = deep_copy(cancellation_policies)
                if confirmed and net:
                    rate["net"] = net
        if confirmed and net:
            hotel["totalNet"] = net
            try:
                numeric = float(net)
            except (TypeError, ValueError):
                numeric = None
            if numeric is not None:
                booking["totalNet"] = numeric
                booking["pendingAmount"] = numeric

    def _apply_room_names(self, expectations_by_type: dict[str, dict], room_names: list[str]) -> None:
        for log_type in ("Search", "Packages", "PreBooking"):
            expectation = expectations_by_type.get(log_type)
            if isinstance(expectation, dict):
                apply_hbs_room_names(expectation, room_names)

    @staticmethod
    def _force_confirmed_get_order(expectation: dict) -> None:
        body = expectation.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return

        booking = body.get("booking")
        if not isinstance(booking, dict):
            return

        booking["status"] = "CONFIRMED"
        booking["modificationPolicies"] = {"cancellation": True, "modification": True}
        hotel = booking.get("hotel")
        if isinstance(hotel, dict):
            hotel["status"] = "CONFIRMED"
            rooms = hotel.get("rooms")
            if isinstance(rooms, list):
                for room in rooms:
                    if isinstance(room, dict):
                        room["status"] = "CONFIRMED"
        if isinstance(body.get("status"), str):
            body["status"] = "CONFIRMED"

    @property
    def log_types(self) -> list[str]:
        return LOG_TYPES


def _apply_hbs_rate_refundability(
    rate: dict,
    price: float,
    is_refundable: bool,
    check_in: str,
    check_out: str,
) -> None:
    """Align rateClass, rateKey token, and cancellationPolicies with refundability.

    HBS adapter treats a future ``cancellationPolicies.from`` as a free-cancel window.
    ``mutate_dates`` shifts template ``from`` values to check-in + 1 day, which makes
    NRF mocks look refundable unless we override here.
    """
    rate["rateClass"] = "REF" if is_refundable else "NRF"
    rate_key = rate.get("rateKey")
    key_token = "NOR" if is_refundable else "NRF"
    if isinstance(rate_key, str):
        updated = rate_key
        for token in ("NRF", "NOR", "REF"):
            updated = updated.replace(f"~~~{token}~~", f"~~~{key_token}~~")
        rate["rateKey"] = updated

    policies = rate.get("cancellationPolicies")
    if not isinstance(policies, list):
        policies = []
        rate["cancellationPolicies"] = policies
    if not policies:
        policies.append({})
    deadline = free_cancel_deadline(check_in)
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        if is_refundable:
            # Free to cancel until the deadline (2 days before check-in); the HBS
            # adapter reads a future `from` as the free-cancel window.
            policy["amount"] = "0"
            policy["from"] = format_cancel_from(deadline)
        else:
            policy["amount"] = str(price)
            policy["from"] = format_cancel_from(PENALTY_ALWAYS_FROM)


def _hbs_package_rates(packages: dict) -> list[dict]:
    """Flatten every rate across the Packages response's rooms, in package order."""
    hotels = (
        packages.get("httpResponse", {})
        .get("body", {})
        .get("hotels", {})
        .get("hotels", [])
    )
    if not isinstance(hotels, list) or not hotels or not isinstance(hotels[0], dict):
        return []
    rooms = hotels[0].get("rooms")
    if not isinstance(rooms, list):
        return []
    rates: list[dict] = []
    for room in rooms:
        if isinstance(room, dict) and isinstance(room.get("rates"), list):
            rates.extend(rate for rate in room["rates"] if isinstance(rate, dict))
    return rates


def _board_name(room_basis: str) -> str:
    mapping = {
        "RO": "ROOM ONLY",
        "BB": "BED AND BREAKFAST",
        "HB": "HALF BOARD",
        "FB": "FULL BOARD",
        "AI": "ALL INCLUSIVE",
    }
    return mapping.get(room_basis.upper(), room_basis)


def _rewrite_hotel_code_in_rates(hotel: dict, new_code: int, old_code: Any) -> None:
    old = str(old_code) if old_code is not None else ""
    new = str(new_code)
    rooms = hotel.get("rooms")
    if not isinstance(rooms, list):
        return
    for room in rooms:
        if not isinstance(room, dict):
            continue
        rates = room.get("rates")
        if not isinstance(rates, list):
            continue
        for rate in rates:
            if not isinstance(rate, dict):
                continue
            rate_key = rate.get("rateKey")
            if isinstance(rate_key, str):
                if old and old != new:
                    rate_key = rate_key.replace(old, new)
                # Also rewrite the hotel-code field embedded in the rateKey, which
                # the template bakes to the default hotel and the code-replace above
                # misses (rateKey hotel id != hotel.code field).
                rate["rateKey"] = _rewrite_rate_key_hotel_id(rate_key, new)


def _normalized_refundable(spec: PackageSpec) -> list[bool]:
    flags = list(spec.refundable)
    while len(flags) < spec.count:
        flags.append(False)
    return flags[: spec.count]


def _normalized_prices(spec: PackageSpec) -> list[float]:
    prices = list(spec.prices)
    while len(prices) < spec.count:
        prices.append(prices[-1] if prices else 0.0)
    return prices[: spec.count]
