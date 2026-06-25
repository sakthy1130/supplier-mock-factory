"""CHC (Choice) supplier plugin.

CHC flows through the shared Derby BTS adapter (``hotels-derby-bts-adapter``) and
returns an OTA/Derby-style payload:

* Search   — ``body.availHotels[].availRoomRates[]`` (each hotel has ``hotelId`` +
  ``stayRange``).
* Packages / PreBooking — ``body.hotelId`` + ``body.roomRates[]``.
* Booking / GetOrder / CancelOrder — ``reservationIds`` /
  ``reservations[].roomRates[]``.

A rate carries ``amountBeforeTax`` / ``amountAfterTax`` (arrays), ``mealPlan``
(same codes as our room basis: RO/BB/HB/FB/AI), ``roomId`` + ``rateId`` identity,
and a ``cancelPolicy`` whose ``cancelPenalties`` express refundability.
"""

from __future__ import annotations

from app.models.scenario import PackageSpec
from app.plugins.base import SupplierMockPlugin
from app.plugins.supplier_currency import apply_chc_supplier_currency
from app.plugins.json_utils import deep_copy, update_fields_recursive

LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

# CHC mealPlan codes line up 1:1 with our room-basis codes.
VALID_MEAL_PLANS = {"RO", "BB", "HB", "FB", "AI"}

# Derby/BTS GO v4 reservation-detail status for a successfully booked order.
# Templates are often captured from a cancelled reservation ("Cancelled"); booking
# tests need the order to read back as confirmed. Change here if the enum differs.
CONFIRMED_ORDER_STATUS = "Confirmed"


class ChcMockPlugin(SupplierMockPlugin):
    code = "CHC"

    def matches_adapter_source(self, source: str) -> bool:
        """CHC flows through the shared Derby BTS adapter, e.g. hotels-derby-bts-adapter."""
        s = source.lower()
        return "derby-bts" in s and "adapter" in s

    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        result = deep_copy(expectation)
        update_fields_recursive(
            result,
            {
                "checkin": lambda _value: check_in,
                "checkout": lambda _value: check_out,
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
        meal = _meal_for_basis(spec.room_basis)

        body = result.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return result

        if log_type == "GetOrder":
            _force_confirmed_get_order(body)
            return result

        if log_type == "Search":
            hotels = body.get("availHotels")
            if isinstance(hotels, list) and hotels:
                target = hotels[0]
                if isinstance(target, dict):
                    if hotel_id:
                        target["hotelId"] = hotel_id
                    self._apply_rates(
                        target.get("availRoomRates"), spec, prices, refundable, meal, log_type
                    )
                    # Single-hotel scenario: keep only the target hotel.
                    body["availHotels"] = [target]
            apply_chc_supplier_currency(result, spec.supplier_currency)
            return result

        # Packages / PreBooking share body.hotelId + body.roomRates.
        if hotel_id:
            body["hotelId"] = hotel_id
        self._apply_rates(body.get("roomRates"), spec, prices, refundable, meal, log_type)
        apply_chc_supplier_currency(result, spec.supplier_currency)
        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        """Align Packages/PreBooking with the Search response.

        The BTS adapter reconciles the availability (Packages) and prebook responses
        against what Search advertised. Our templates are captured from separate real
        sessions, so they disagree on occupancy (``roomCriteria``) and rate identity
        (``roomId``/``rateId``). Search is the response that matched the live request,
        so we treat it as the source of truth and copy its primary-rate occupancy +
        identity onto the downstream responses. Without this, the adapter drops every
        rate and returns zero packages.
        """
        primary = _search_primary_rate(expectations_by_type.get("Search"))
        if primary is None:
            return
        room_id = primary.get("roomId")
        rate_id = primary.get("rateId")
        occupancy = primary.get("roomCriteria")

        for log_type in ("Packages", "PreBooking"):
            expectation = expectations_by_type.get(log_type)
            if not isinstance(expectation, dict):
                continue
            body = expectation.get("httpResponse", {}).get("body")
            if not isinstance(body, dict):
                continue

            if isinstance(occupancy, dict):
                body["roomCriteria"] = deep_copy(occupancy)

            rates = body.get("roomRates")
            if isinstance(rates, list):
                for rate in rates:
                    if not isinstance(rate, dict):
                        continue
                    if room_id is not None:
                        rate["roomId"] = room_id
                    if rate_id is not None:
                        rate["rateId"] = rate_id
                    if isinstance(occupancy, dict):
                        rate["roomCriteria"] = deep_copy(occupancy)

            candidate = body.get("productCandidate")
            if isinstance(candidate, dict):
                if room_id is not None:
                    candidate["roomId"] = room_id
                if rate_id is not None:
                    candidate["rateId"] = rate_id

    def _apply_rates(
        self,
        rates: object,
        spec: PackageSpec,
        prices: list[float],
        refundable: list[bool],
        meal: str,
        log_type: str,
    ) -> None:
        if not isinstance(rates, list) or not rates or not isinstance(rates[0], dict):
            return
        template_rate = deep_copy(rates[0])
        new_rates: list[dict] = []
        for index in range(spec.count):
            rate = deep_copy(template_rate)
            price = prices[index]
            rate["amountBeforeTax"] = [price]
            rate["amountAfterTax"] = [price]
            rate["mealPlan"] = meal
            rate["currency"] = spec.supplier_currency
            _apply_cancel_policy(rate, refundable[index], log_type)
            new_rates.append(rate)
        rates[:] = new_rates

    @property
    def log_types(self) -> list[str]:
        return LOG_TYPES


_DEFAULT_CANCEL_DEADLINE = {
    "offsetTimeDropType": "BeforeArrival",
    "offsetTimeUnit": "D",
    "offsetTimeValue": 1,
    "deadline": "4PM",
}


def _apply_cancel_policy(rate: dict, is_refundable: bool, log_type: str) -> None:
    """Normalize cancel penalties on supplier rate payloads.

    Keep template Derby ``cancelPolicy.code`` (e.g. ``4PM1D100P_100P``). Strip no-show
    penalties and ensure ``cancelDeadline`` is present. Contract
    ``isCancellationPolicyOneSlot=true`` collapses multi-slot codes to one adapter tier.
    """
    del log_type  # same shaping for Search, Packages, and PreBooking
    policy = rate.get("cancelPolicy")
    if not isinstance(policy, dict):
        return
    penalties = policy.get("cancelPenalties")
    if not isinstance(penalties, list):
        return

    kept: list[dict] = []
    for penalty in penalties:
        if not isinstance(penalty, dict) or penalty.get("noShow"):
            continue
        if not isinstance(penalty.get("cancelDeadline"), dict):
            penalty["cancelDeadline"] = deep_copy(_DEFAULT_CANCEL_DEADLINE)
        penalty["cancellable"] = True
        charge = penalty.get("penaltyCharge")
        if isinstance(charge, dict):
            charge["percent"] = 0 if is_refundable else 100
        kept.append(penalty)

    if not kept:
        kept.append(
            {
                "noShow": False,
                "cancellable": True,
                "cancelDeadline": deep_copy(_DEFAULT_CANCEL_DEADLINE),
                "penaltyCharge": {
                    "chargeBase": "FullStay",
                    "percent": 0 if is_refundable else 100,
                },
            }
        )

    policy["cancelPenalties"] = kept[:1]

    # Derby ``getRefundability`` treats any non-AD code (e.g. ``4PM1D100P_100P``) as refundable.
    policy["code"] = "AD0_0" if is_refundable else "AD100P_100P"


def _force_confirmed_get_order(body: dict) -> None:
    """Normalize GetOrder (reservation detail) so the booked order reads as confirmed.

    Templates are frequently captured from a cancelled reservation; for booking tests
    the order must come back confirmed.
    """
    reservations = body.get("reservations")
    if not isinstance(reservations, list):
        return
    for reservation in reservations:
        if isinstance(reservation, dict):
            reservation["status"] = CONFIRMED_ORDER_STATUS
            reservation["result"] = "Successful"


def _search_primary_rate(search: object) -> dict | None:
    """First availRoomRate of the first availHotel in a Search expectation."""
    if not isinstance(search, dict):
        return None
    body = search.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return None
    hotels = body.get("availHotels")
    if not isinstance(hotels, list) or not hotels or not isinstance(hotels[0], dict):
        return None
    rates = hotels[0].get("availRoomRates")
    if isinstance(rates, list) and rates and isinstance(rates[0], dict):
        return rates[0]
    return None


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
