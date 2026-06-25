"""RHK (RateHawk) supplier plugin. Port RhkAdapter* / WorldOTA B2B patterns."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.scenario import PackageSpec
from app.plugins.base import SupplierMockPlugin
from app.plugins.room_names import apply_rhk_room_names, normalized_room_names
from app.plugins.supplier_currency import apply_rhk_supplier_currency
from app.plugins.json_utils import deep_copy, replace_in_json_strings, update_fields_recursive

LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

MEAL_BY_ROOM_BASIS = {
    "RO": "nomeal",
    "BB": "breakfast",
    "HB": "halfboard",
    "FB": "fullboard",
    "AI": "allinclusive",
}


class RhkMockPlugin(SupplierMockPlugin):
    code = "RHK"

    def matches_adapter_source(self, source: str) -> bool:
        """Match e.g. hotels-rhk-adapter-service-staging."""
        s = source.lower()
        return "rhk" in s and "adapter" in s

    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        result = deep_copy(expectation)
        update_fields_recursive(
            result,
            {
                "checkin_at": lambda _value: check_in,
                "checkout_at": lambda _value: check_out,
                "checkin": lambda _value: check_in,
                "checkout": lambda _value: check_out,
            },
        )

        cp_date = (datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        for old_cp in _collect_cancellation_dates(result):
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
        result = deep_copy(expectation)
        refundable = _normalized_refundable(spec)
        prices = _normalized_prices(spec)
        meal = _meal_for_basis(spec.room_basis)
        hid = int(hotel_id) if hotel_id.isdigit() else None

        body = result.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return result

        if log_type == "GetOrder":
            self._force_confirmed_get_order(result)

        data = body.get("data")
        if isinstance(data, dict):
            hotels = data.get("hotels")
            if isinstance(hotels, list) and hotels:
                self._apply_hotel_mutation(hotels[0], spec, prices, refundable, meal, hid)
                if log_type == "Search":
                    data["hotels"] = [hotels[0]]
            orders = data.get("orders")
            if isinstance(orders, list) and orders and isinstance(orders[0], dict):
                orders[0]["checkin_at"] = check_in
                orders[0]["checkout_at"] = check_out
                hotel_data = orders[0].get("hotel_data")
                if isinstance(hotel_data, dict) and hid is not None:
                    hotel_data["hid"] = hid

        apply_rhk_supplier_currency(result, spec.supplier_currency)
        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        room_names = normalized_room_names(spec)
        if room_names:
            for log_type in ("Search", "Packages", "PreBooking"):
                expectation = expectations_by_type.get(log_type)
                if isinstance(expectation, dict):
                    apply_rhk_room_names(expectation, room_names)

        packages = expectations_by_type.get("Packages")
        prebook = expectations_by_type.get("PreBooking")
        if not packages or not prebook:
            return

        pkg_body = packages.get("httpResponse", {}).get("body")
        if not isinstance(pkg_body, dict):
            return
        primary_rate = _first_rate_from_data(pkg_body.get("data"))
        if not primary_rate:
            return

        match_hash = primary_rate.get("match_hash")
        if not match_hash:
            return

        http_request = prebook.setdefault("httpRequest", {})
        body = http_request.setdefault("body", {})
        if isinstance(body, dict):
            payload = body.setdefault("json", {})
            if isinstance(payload, dict):
                payload["match_hash"] = match_hash
                if "hash" in payload:
                    payload["hash"] = match_hash

        pre_body = prebook.get("httpResponse", {}).get("body")
        if isinstance(pre_body, dict):
            pre_rate = _first_rate_from_data(pre_body.get("data"))
            if isinstance(pre_rate, dict):
                pre_rate["match_hash"] = match_hash
                if primary_rate.get("book_hash"):
                    pre_rate["book_hash"] = primary_rate["book_hash"]

        search = expectations_by_type.get("Search")
        if not isinstance(search, dict):
            return
        search_body = search.get("httpResponse", {}).get("body")
        if not isinstance(search_body, dict):
            return
        search_rate = _first_rate_from_data(search_body.get("data"))
        if isinstance(search_rate, dict):
            search_rate["match_hash"] = match_hash
            if primary_rate.get("search_hash"):
                search_rate["search_hash"] = primary_rate["search_hash"]

    def _apply_hotel_mutation(
        self,
        hotel: dict,
        spec: PackageSpec,
        prices: list[float],
        refundable: list[bool],
        meal: str,
        hid: int | None,
    ) -> None:
        if hid is not None:
            hotel["hid"] = hid

        rates = hotel.get("rates")
        if not isinstance(rates, list) or not rates:
            return

        template_rate = deep_copy(rates[0])
        room_names = normalized_room_names(spec)
        new_rates = []
        for index in range(spec.count):
            rate = deep_copy(template_rate)
            price = prices[index]
            price_str = f"{price:.2f}"
            is_refundable = refundable[index]
            rate["meal"] = meal
            if "room_name" in rate:
                rate["room_name"] = room_names[index]
            meal_data = rate.get("meal_data")
            if isinstance(meal_data, dict):
                meal_data["value"] = meal
                meal_data["has_breakfast"] = meal != "nomeal"
            rate["daily_prices"] = [price_str]
            payment_options = rate.get("payment_options")
            if isinstance(payment_options, dict):
                pay_types = payment_options.get("payment_types")
                if isinstance(pay_types, list) and pay_types and isinstance(pay_types[0], dict):
                    pay_types[0]["amount"] = price_str
                    pay_types[0]["show_amount"] = price_str
            penalties = rate.get("cancellation_penalties")
            if isinstance(penalties, dict):
                policies = penalties.get("policies")
                if isinstance(policies, list):
                    for policy in policies:
                        if isinstance(policy, dict) and policy.get("end_at") is None:
                            policy["amount_charge"] = "0.00" if is_refundable else price_str
                            policy["amount_show"] = "0.00" if is_refundable else price_str
            new_rates.append(rate)

        hotel["rates"] = new_rates

    @staticmethod
    def _force_confirmed_get_order(expectation: dict) -> None:
        body = expectation.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return
        data = body.get("data")
        if not isinstance(data, dict):
            return
        orders = data.get("orders")
        if not isinstance(orders, list):
            return
        for order in orders:
            if not isinstance(order, dict):
                continue
            order["status"] = "completed"
            order["is_cancellable"] = True

    @property
    def log_types(self) -> list[str]:
        return LOG_TYPES


def _first_rate_from_data(data: object) -> dict | None:
    if isinstance(data, dict):
        hotels = data.get("hotels")
        if isinstance(hotels, list) and hotels:
            return _first_rate_from_hotel(hotels[0])
    if isinstance(data, list) and data:
        return _first_rate_from_hotel(data[0])
    return None


def _first_rate_from_hotel(hotel: object) -> dict | None:
    if not isinstance(hotel, dict):
        return None
    rates = hotel.get("rates")
    if isinstance(rates, list) and rates and isinstance(rates[0], dict):
        return rates[0]
    return None


def _collect_cancellation_dates(expectation: dict) -> list[str]:
    dates: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"start_at", "end_at"} and isinstance(value, str) and "T" in value:
                    dates.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(expectation)
    return dates


def _meal_for_basis(room_basis: str) -> str:
    return MEAL_BY_ROOM_BASIS.get(room_basis.upper(), "nomeal")


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
