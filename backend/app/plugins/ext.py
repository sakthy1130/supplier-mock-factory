"""EXT (Extranet) supplier plugin. NET supplier with per-room dynamic pricing."""

from __future__ import annotations

from app.models.scenario import PackageSpec
from app.plugins.base import SupplierMockPlugin
from app.plugins.room_names import normalized_room_basis
from app.plugins.supplier_currency import apply_chc_supplier_currency
from app.plugins.json_utils import deep_copy, update_fields_recursive

LOG_TYPES = [
    "Search",
    "Packages",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

VALID_MEAL_PLANS = {"RO", "BB", "HB", "FB", "AI"}


class ExtMockPlugin(SupplierMockPlugin):
    code = "EXT"

    def matches_adapter_source(self, source: str) -> bool:
        """Match e.g. extranet-adapter or similar."""
        s = source.lower()
        return "extranet" in s and "adapter" in s

    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        result = deep_copy(expectation)
        update_fields_recursive(
            result,
            {
                "checkin": lambda _value: check_in,
                "checkout": lambda _value: check_out,
                "checkIn": lambda _value: check_in,
                "checkOut": lambda _value: check_out,
                "checkin_at": lambda _value: check_in,
                "checkout_at": lambda _value: check_out,
                "arrival_date": lambda _value: check_in,
                "departure_date": lambda _value: check_out,
            },
        )
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
        result = self.mutate_dates(expectation, check_in, check_out)
        prices = _normalized_prices(spec)
        refundable = _normalized_refundable(spec)
        meals = [_meal_for_basis(basis) for basis in normalized_room_basis(spec)]

        body = result.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return result

        if log_type == "GetOrder":
            _force_confirmed_get_order(body)
            return result

        # Update hotel ID if present
        if hotel_id and "hotelId" in body:
            body["hotelId"] = hotel_id

        # Apply prices and room basis to rates/rooms structure
        self._apply_package_mutations(body, spec, prices, refundable, meals)

        apply_chc_supplier_currency(result, spec.supplier_currency)
        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        """Propagate Search primary rate identifiers to downstream responses if needed.

        EXT's Search response should be aligned with Packages/Booking for consistent pricing.
        """
        # For now, minimal propagation. Can be expanded if EXT templates require linkage
        # similar to HBS/CHC (e.g., syncing rate IDs or pricing structures).
        pass

    def _apply_package_mutations(self, body: dict, spec: PackageSpec, prices: list[float], refundable: list[bool], meals: list[str]) -> None:
        """Apply price, meal plan, and refundability mutations to rate structures.

        EXT can structure rates in multiple ways; this handles common patterns:
        - body.rooms[] (hotel-level rooms)
        - body.rates[] (direct rate array)
        - body.roomRates[] (CHC-style)
        """
        # Try hotel-level rooms
        rooms = body.get("rooms")
        if isinstance(rooms, list) and rooms:
            self._apply_rooms_mutations(rooms, spec, prices, refundable, meals)
            return

        # Try direct rates array
        rates = body.get("rates")
        if isinstance(rates, list) and rates:
            self._apply_rates_mutations(rates, spec, prices, refundable, meals)
            return

        # Try CHC-style roomRates
        room_rates = body.get("roomRates")
        if isinstance(room_rates, list) and room_rates:
            self._apply_rates_mutations(room_rates, spec, prices, refundable, meals)
            return

    def _apply_rooms_mutations(self, rooms: list, spec: PackageSpec, prices: list[float], refundable: list[bool], meals: list[str]) -> None:
        """Apply mutations to body.rooms[] structure (e.g., hotel → rooms → rates)."""
        if not rooms or not isinstance(rooms[0], dict):
            return
        template_room = deep_copy(rooms[0])
        new_rooms = []
        for index in range(spec.count):
            room = deep_copy(template_room)
            price = prices[index]
            room["price"] = price
            room["total"] = price
            room["board"] = meals[index]
            room["mealPlan"] = meals[index]
            _apply_cancel_policy(room, refundable[index])
            new_rooms.append(room)
        rooms[:] = new_rooms

    def _apply_rates_mutations(self, rates: list, spec: PackageSpec, prices: list[float], refundable: list[bool], meals: list[str]) -> None:
        """Apply mutations to rates[] or roomRates[] structures."""
        if not rates or not isinstance(rates[0], dict):
            return
        template_rate = deep_copy(rates[0])
        new_rates = []
        for index in range(spec.count):
            rate = deep_copy(template_rate)
            price = prices[index]
            # Try common price field names
            rate["price"] = price
            rate["total"] = price
            rate["amount"] = price
            rate["amountBeforeTax"] = [price]
            rate["amountAfterTax"] = [price]
            rate["board"] = meals[index]
            rate["mealPlan"] = meals[index]
            _apply_cancel_policy(rate, refundable[index])
            new_rates.append(rate)
        rates[:] = new_rates

    @property
    def log_types(self) -> list[str]:
        return LOG_TYPES


def _apply_cancel_policy(obj: dict, is_refundable: bool) -> None:
    """Normalize cancellation policy on rate payloads."""
    policy = obj.get("cancelPolicy")
    if not isinstance(policy, dict):
        return
    penalties = policy.get("cancelPenalties")
    if not isinstance(penalties, list):
        return
    for penalty in penalties:
        if isinstance(penalty, dict):
            charge = penalty.get("penaltyCharge")
            if isinstance(charge, dict):
                charge["percent"] = 0 if is_refundable else 100


def _force_confirmed_get_order(body: dict) -> None:
    """Normalize GetOrder so the booked order reads as confirmed."""
    reservations = body.get("reservations")
    if not isinstance(reservations, list):
        return
    for reservation in reservations:
        if isinstance(reservation, dict):
            reservation["status"] = "Confirmed"
            reservation["result"] = "Successful"


def _meal_for_basis(room_basis: str) -> str:
    code = room_basis.upper()
    return code if code in VALID_MEAL_PLANS else "RO"


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
