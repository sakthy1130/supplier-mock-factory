"""Shared mock plugin for every supplier behind ``hotels-derby-bts-adapter``.

CHC (Choice) and HIL (Hilton) both reach Enigma through the same Derby BTS adapter and
return the same OTA/Derby-style payload, so one mutator serves both:

* Search   — ``body.availHotels[].availRoomRates[]`` (each hotel has ``hotelId`` +
  ``stayRange``).
* Packages / PreBooking — ``body.hotelId`` + ``body.roomRates[]``.
* Booking / GetOrder / CancelOrder — ``reservationIds`` /
  ``reservations[].roomRates[]``.

A rate carries ``amountBeforeTax`` / ``amountAfterTax`` (arrays the adapter *sums*, so
one element is the stay total), ``mealPlan`` (RO/BB/HB/FB/AI), ``roomId`` + ``rateId``
identity, and a ``cancelPolicy`` whose ``code`` — not its ``cancelPenalties`` — is what
the adapter reads to decide refundability. See ``_apply_cancel_policy``.

Because the adapter is shared, a log row's ``source`` cannot say which supplier it
belongs to; ``claims_log_payload`` uses ``header.supplierId`` instead.
"""

from __future__ import annotations

from app.models.scenario import PackageSpec, PreBookingStatus
from app.plugins.base import SupplierMockPlugin
from app.plugins.prebooking import prebooking_effective_price
from app.plugins.room_names import normalized_room_basis
from app.ingest.expectation_builder import payload_hotel_id as log_hotel_id
from app.ingest.expectation_builder import payload_supplier_id as log_supplier_id
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

# Derby mealPlan codes that map 1:1 onto our room-basis codes. SupplierRoomBasis in the
# adapter accepts more (AL, SC, DB, BL, LO, LD, BB1..BB10) but collapses them onto these
# five, and silently falls back to RO for anything it does not recognise.
VALID_MEAL_PLANS = {"RO", "BB", "HB", "FB", "AI"}

# Derby/BTS GO v4 reservation-detail status for a successfully booked order.
# Templates are often captured from a cancelled reservation ("Cancelled"); booking
# tests need the order to read back as confirmed. Change here if the enum differs.
CONFIRMED_ORDER_STATUS = "Confirmed"


class DerbyBtsMockPlugin(SupplierMockPlugin):
    """Derby BTS mutator for one supplier. Subclasses only supply identity."""

    # Source is the same string for every Derby supplier, so attribution needs the payload.
    disambiguate_by_payload = True

    #: ``header.supplierId`` in this supplier's Derby payloads, e.g. "CHOICE", "HILTON".
    payload_supplier_id: str = ""

    def matches_adapter_source(self, source: str) -> bool:
        """Matches the shared Derby BTS adapter, e.g. hotels-derby-bts-adapter.

        True for every Derby supplier — ``claims_log_payload`` is what separates them.
        """
        s = source.lower()
        return "derby-bts" in s and "adapter" in s

    def claims_log_payload(self, full_log: dict) -> bool:
        """Attribute a Derby row by ``header.supplierId``.

        Every Derby request and response carries it (the adapter builds it in
        ``SupplierUtils.createRequestHeader``), so a row without one is a row we cannot
        tell apart from a sibling supplier's — drop it rather than guess.
        """
        found = log_supplier_id(full_log)
        if not found or not self.payload_supplier_id:
            return False
        return found.strip().upper() == self.payload_supplier_id.upper()

    def payload_hotel_id(self, full_log: dict) -> str | None:
        """Derby keeps it on the hotel entry for Search and at body level elsewhere."""
        return log_hotel_id(full_log)

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

    def supplier_hotel_id(self, hotel_id: str) -> str:
        """The hotel id the supplier itself sees.

        The mapping service returns it prefixed ("HL-DXBJB", "GI-RUHSK") while the
        adapter calls Derby with only the part after the dash. Echoing the prefixed id
        back describes a hotel the supplier was never asked about, and the adapter's
        per-hotel lookups miss — which surfaces as zero packages and no error. Opt in
        per supplier via mock_config.strip_hotel_id_prefix.
        """
        if not hotel_id or "-" not in hotel_id:
            return hotel_id
        from app.services.supplier_service import UnknownSupplierError, get_supplier_config

        try:
            strip = get_supplier_config(self.code).mock_config.strip_hotel_id_prefix
        except UnknownSupplierError:
            return hotel_id
        return hotel_id.split("-", 1)[1] if strip else hotel_id

    def mutate_packages(
        self,
        expectation: dict,
        spec: PackageSpec,
        hotel_id: str,
        check_in: str,
        check_out: str,
        log_type: str,
    ) -> dict:
        hotel_id = self.supplier_hotel_id(hotel_id)
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

        if log_type == "Search":
            hotels = body.get("availHotels")
            if isinstance(hotels, list) and hotels:
                target = hotels[0]
                if isinstance(target, dict):
                    if hotel_id:
                        target["hotelId"] = hotel_id
                    self._apply_rates(
                        target.get("availRoomRates"), spec, prices, refundable, meals, log_type
                    )
                    # Single-hotel scenario: keep only the target hotel.
                    body["availHotels"] = [target]
            apply_chc_supplier_currency(result, spec.supplier_currency)
            return result

        # Packages / PreBooking share body.hotelId + body.roomRates, and keep occupancy
        # in a single body-level block rather than per rate.
        if hotel_id:
            body["hotelId"] = hotel_id
        if isinstance(body.get("roomCriteria"), dict):
            body["roomCriteria"] = deep_copy(spec.room_criteria)
        self._apply_rates(body.get("roomRates"), spec, prices, refundable, meals, log_type)
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
        search_rates = _search_rates(expectations_by_type.get("Search"))
        if not search_rates:
            return
        primary = search_rates[0]
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
                for index, rate in enumerate(rates):
                    if not isinstance(rate, dict):
                        continue
                    # Pair package i with SEARCH rate i, not with the primary. Copying
                    # the primary onto every rate gave a multi-package scenario N rates
                    # sharing one roomId/rateId, which the adapter collapses back to a
                    # single package. Beyond the search rates (never happens once both
                    # come from the same spec.count) fall back to the primary, which is
                    # still a rate the adapter knows.
                    source = search_rates[index] if index < len(search_rates) else primary
                    if source.get("roomId") is not None:
                        rate["roomId"] = source["roomId"]
                    if source.get("rateId") is not None:
                        rate["rateId"] = source["rateId"]
                    if isinstance(occupancy, dict):
                        rate["roomCriteria"] = deep_copy(occupancy)

        self._apply_prebooking(expectations_by_type, spec, search_rates)

    def _apply_prebooking(
        self,
        expectations_by_type: dict[str, dict],
        spec: PackageSpec,
        search_rates: list[dict],
    ) -> None:
        """Narrow the prebook body to the ONE rate being booked, and apply the status.

        Derby's real prebook response carries a single roomRates entry plus the
        productCandidate naming it — a price check answers about one rate, not the whole
        availability list. Replaying every rate invites the adapter to settle on one that
        was never under test.

        The Derby body has no status field, so like EXT each status is structural:
          available     -> the booked rate, at the price Packages offered
          price_changed -> the booked rate, repriced
          sold_out      -> no rate at all; the one asked about is gone
        """
        prebook = expectations_by_type.get("PreBooking")
        if not isinstance(prebook, dict):
            return
        body = prebook.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return
        rates = body.get("roomRates")
        if not isinstance(rates, list) or not rates:
            return

        idx = spec.booking_package_index if spec.booking_package_index is not None else 0
        idx = min(idx, len(rates) - 1)
        selected = rates[idx]

        # The candidate is whichever rate is being pre-booked — it used to be pinned to
        # the primary, which named the wrong rate whenever the booked package was not the
        # first. It is set even for sold_out, where it echoes the rate that was ASKED
        # about; leaving the template's captured rate there would name one this scenario
        # never offered.
        candidate = body.get("productCandidate")
        if isinstance(candidate, dict) and isinstance(selected, dict):
            if selected.get("roomId") is not None:
                candidate["roomId"] = selected["roomId"]
            if selected.get("rateId") is not None:
                candidate["rateId"] = selected["rateId"]

        if spec.prebooking_status is PreBookingStatus.sold_out:
            body["roomRates"] = []
            return

        body["roomRates"] = [selected]

        if spec.prebooking_status is not PreBookingStatus.price_changed:
            return
        changed = prebooking_effective_price(spec, _normalized_prices(spec))
        if changed is None or not isinstance(selected, dict):
            return
        # The adapter SUMS these arrays, so one element is the whole stay total.
        selected["amountBeforeTax"] = [changed]
        selected["amountAfterTax"] = [changed]

    def _apply_rates(
        self,
        rates: object,
        spec: PackageSpec,
        prices: list[float],
        refundable: list[bool],
        meals: list[str],
        log_type: str,
    ) -> None:
        if not isinstance(rates, list) or not rates or not isinstance(rates[0], dict):
            return
        template_rate = deep_copy(rates[0])
        room_ids = list(spec.supplier_room_ids)
        new_rates: list[dict] = []
        for index in range(spec.count):
            rate = deep_copy(template_rate)
            price = prices[index]
            rate["amountBeforeTax"] = [price]
            rate["amountAfterTax"] = [price]
            rate["mealPlan"] = meals[index]
            rate["currency"] = spec.supplier_currency
            # The adapter names rooms from its own per-hotel catalogue and DROPS any rate
            # whose roomId is not in it — no error, just an empty package list. The
            # captured template's room ids belong to whichever hotel it was captured
            # from, so they are wrong for every other hotel. Cycling also stops a
            # count > 1 scenario emitting N rates that all share rates[0]'s room id.
            if room_ids:
                rate["roomId"] = room_ids[index % len(room_ids)]
            # Occupancy gate: the adapter buckets rates by roomCriteria and drops any
            # availability that has no rate matching the searched occupancy — silently,
            # with zero results and no error. Stamp it so the mock answers the search
            # that is actually run rather than the one the template was captured from.
            if "roomCriteria" in rate:
                rate["roomCriteria"] = deep_copy(spec.room_criteria)
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
        # Overwrite the deadline rather than only filling a missing one. Search and
        # Packages are ingested from different sessions, so the templates disagree (5
        # days before arrival vs 1), and that drift shows up in a scenario where every
        # other field matches. Nothing in the adapter compares the two deadlines — the
        # rate identity key is rateId-roomId-refundability — but a mock that describes
        # one policy in search and another in availability is wrong on its own terms.
        penalty["cancelDeadline"] = deep_copy(_DEFAULT_CANCEL_DEADLINE)
        penalty["cancellable"] = True
        charge = penalty.get("penaltyCharge")
        if isinstance(charge, dict):
            charge["percent"] = 0 if is_refundable else 100
            # One template carries nights as "1" and the other as 1; the field is
            # numeric, so make both sides agree on the type too.
            if "nights" in charge:
                try:
                    charge["nights"] = int(charge["nights"])
                except (TypeError, ValueError):
                    charge["nights"] = 1
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


def _search_rates(search: object) -> list[dict]:
    """availRoomRates of the first availHotel in a Search expectation."""
    if not isinstance(search, dict):
        return []
    body = search.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return []
    hotels = body.get("availHotels")
    if not isinstance(hotels, list) or not hotels or not isinstance(hotels[0], dict):
        return []
    rates = hotels[0].get("availRoomRates")
    if not isinstance(rates, list):
        return []
    return [rate for rate in rates if isinstance(rate, dict)]


def _search_primary_rate(search: object) -> dict | None:
    """First availRoomRate of the first availHotel in a Search expectation."""
    rates = _search_rates(search)
    return rates[0] if rates else None


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
