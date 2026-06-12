"""HBS supplier plugin. Port SupplierRankingHbsJsonUtils."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from app.models.scenario import PackageSpec
from app.plugins.base import SupplierMockPlugin
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
            return self._mutate_search_hotel(expectation, hotel_id)

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
        new_rates = []
        for index in range(spec.count):
            rate = deep_copy(rates[index % len(rates)])
            price = prices[index]
            is_refundable = refundable[index]
            rate["net"] = str(price)
            rate["boardCode"] = spec.room_basis
            rate["boardName"] = _board_name(spec.room_basis)
            rate["rateClass"] = "REF" if is_refundable else "NRF"
            if isinstance(rate.get("rateKey"), str):
                rate["rateKey"] = rate["rateKey"].replace(" RO|", f" {spec.room_basis}|")
                if index >= len(rates):
                    rate["rateKey"] = _with_unique_rate_key_suffix(rate["rateKey"], index)
            cancellation_policies = rate.get("cancellationPolicies")
            if isinstance(cancellation_policies, list):
                for policy in cancellation_policies:
                    if isinstance(policy, dict):
                        policy["amount"] = str(price)
            new_rates.append(rate)

        room["rates"] = new_rates
        if isinstance(hotel, dict):
            hotel["rooms"] = [room]

        if prices:
            primary_price = str(prices[0])
            serialized = json.dumps(result)
            old_net = str(template_rate.get("net", ""))
            if old_net:
                serialized = serialized.replace(old_net, primary_price)
            result = json.loads(serialized)

        return result

    def _mutate_search_hotel(self, expectation: dict, hotel_id: str) -> dict:
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

        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
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
        pkg_rates = pkg_rooms[0].get("rates") if isinstance(pkg_rooms[0], dict) else None
        if not isinstance(pkg_rates, list) or not pkg_rates:
            return

        primary_rate = pkg_rates[0]
        primary_rate_key = primary_rate.get("rateKey")
        primary_net = str(primary_rate.get("net", ""))
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
            if primary_rate.get("rateClass"):
                rate["rateClass"] = primary_rate["rateClass"]
            policies = rate.get("cancellationPolicies")
            if isinstance(policies, list) and primary_net:
                for policy in policies:
                    if isinstance(policy, dict):
                        policy["amount"] = primary_net

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
        synced_rate = deep_copy(primary_rate)
        search_rooms[0]["rates"] = [synced_rate]
        search_hotels[0]["rooms"] = [search_rooms[0]]

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
            if isinstance(rate_key, str) and old and old != new:
                rate["rateKey"] = rate_key.replace(old, new)


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
