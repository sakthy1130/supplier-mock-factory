"""EXT (Extranet) supplier plugin. NET supplier with distribution-based pricing."""

from __future__ import annotations

import uuid

from app.core.cancel_policy import FREE_CANCEL_DAYS_BEFORE_CHECKIN
from app.models.scenario import PackageSpec
from app.plugins.base import SupplierMockPlugin
from app.plugins.room_names import normalized_room_basis
from app.plugins.json_utils import deep_copy, update_fields_recursive

LOG_TYPES = [
    "Search",
    "Packages",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

VALID_MEAL_PLANS = {"RO", "BB", "HB", "FB", "AI", "IF", "SR", "IR"}


class ExtMockPlugin(SupplierMockPlugin):
    code = "EXT"

    def matches_adapter_source(self, source: str) -> bool:
        """Match e.g. extranet-adapter, hotels-extranet-search, etc."""
        s = source.lower()
        return "extranet" in s

    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        result = deep_copy(expectation)
        update_fields_recursive(
            result,
            {
                "checkInDate": lambda _value: check_in,
                "checkOutDate": lambda _value: check_out,
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

        body = result.get("httpResponse", {}).get("body")
        if not isinstance(body, dict):
            return result

        # Handle Search and Packages: body.body[].accommodations[].distributions[]
        if log_type in ("Search", "Packages"):
            body_list = body.get("body")
            if isinstance(body_list, list) and body_list:
                hotel = body_list[0]
                if isinstance(hotel, dict):
                    if hotel_id:
                        hotel["hotelId"] = hotel_id
                    self._mutate_accommodations(hotel, spec, check_in, check_out)
                    self._update_currency(hotel, spec.supplier_currency)

        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        """Sync the selected package's price/board/room into the Booking and
        GetOrder mocks so a retrieved order matches the picked package.

        The EXT booking-flow request matchers are path+method only and the
        accommodation id is never echoed, so only the response values need
        aligning (no id reuse required).
        """
        idx = spec.booking_package_index
        if idx is None:
            return

        packages = expectations_by_type.get("Packages")
        if not isinstance(packages, dict):
            return
        hotel = _ext_packages_hotel(packages)
        if not isinstance(hotel, dict):
            return
        accommodations = hotel.get("accommodations")
        if not isinstance(accommodations, list) or idx >= len(accommodations):
            return
        acc = accommodations[idx]
        if not isinstance(acc, dict):
            return
        distributions = acc.get("distributions")
        dist = distributions[0] if isinstance(distributions, list) and distributions else {}
        if not isinstance(dist, dict):
            dist = {}

        total_price = acc.get("totalPrice")
        net_price = acc.get("netPrice", total_price)
        currency = acc.get("currency")
        room_name = dist.get("roomName")
        board = dist.get("board")
        hotel_id = hotel.get("hotelId")

        # _ext_apply_values only overwrites keys already present on the target, so
        # confirm (body.body: totalPrice/netPrice/currency) and getOrder
        # (reservations[0]: totalPrice/roomName/board/hotelId) each take what fits.
        values = {
            "totalPrice": total_price,
            "netPrice": net_price,
            "currency": currency,
            "roomName": room_name,
            "board": board,
            "hotelId": hotel_id,
        }

        # Both Booking (confirm) and GetOrder wrap the booking under body.body
        # (real EXT shape). The adapter reads body.body.bookingId — a flat or
        # reservations[] body yields an empty bId / NullPointerException
        # (E3025.2 / E9999.1).
        for log_type in ("Booking", "GetOrder"):
            expectation = expectations_by_type.get(log_type)
            if not isinstance(expectation, dict):
                continue
            inner = expectation.get("httpResponse", {}).get("body", {}).get("body")
            if isinstance(inner, dict):
                _ext_apply_values(inner, values)

    def _update_currency(self, hotel: dict, currency: str) -> None:
        """Update currency in all accommodations and distributions."""
        accommodations = hotel.get("accommodations")
        if not isinstance(accommodations, list):
            return

        for accommodation in accommodations:
            if not isinstance(accommodation, dict):
                continue

            # Update accommodation-level currency
            accommodation["currency"] = currency

            # Update distribution-level currency (if present)
            distributions = accommodation.get("distributions", [])
            if isinstance(distributions, list):
                for distribution in distributions:
                    if isinstance(distribution, dict):
                        # Note: EXT distributions may have currency in priceDetails or elsewhere
                        # but the main currency field is at accommodation level
                        pass

    def _mutate_accommodations(
        self,
        hotel: dict,
        spec: PackageSpec,
        check_in: str,
        check_out: str,
    ) -> None:
        """Mutate accommodations array to match requested packages."""
        accommodations = hotel.get("accommodations")
        if not isinstance(accommodations, list) or not accommodations:
            return

        template_accommodation = deep_copy(accommodations[0])
        new_accommodations = []

        prices = _normalized_prices(spec)
        refundable = _normalized_refundable(spec)
        meals = [_meal_for_basis(basis) for basis in normalized_room_basis(spec)]
        room_names = list(spec.room_names)

        # Calculate nights
        from datetime import datetime
        check_in_dt = datetime.strptime(check_in, "%Y-%m-%d")
        check_out_dt = datetime.strptime(check_out, "%Y-%m-%d")
        nights = (check_out_dt - check_in_dt).days

        for index in range(spec.count):
            accommodation = deep_copy(template_accommodation)
            accommodation["id"] = str(uuid.uuid4())
            accommodation["checkInDate"] = check_in
            accommodation["checkOutDate"] = check_out
            accommodation["nights"] = nights

            # Update price fields (UI passes TOTAL stay price, not per-night)
            stay_total_price = prices[index]

            # Accommodation level: use total stay price as-is
            accommodation["initialPrice"] = stay_total_price
            accommodation["totalPrice"] = stay_total_price
            accommodation["netPrice"] = stay_total_price
            accommodation["noRefundable"] = not refundable[index]

            # Update distributions (rooms in EXT terminology)
            distributions = accommodation.get("distributions", [])
            if isinstance(distributions, list) and distributions:
                template_dist = deep_copy(distributions[0])
                template_dist["board"] = meals[index]
                template_dist["roomName"] = room_names[index]

                # Update price details in distribution (use total stay price)
                price_details = template_dist.get("priceDetails", {})
                if isinstance(price_details, dict):
                    price_details["initialPrice"] = stay_total_price
                    price_details["netPrice"] = stay_total_price
                    price_details["totalPrice"] = stay_total_price

                # Calculate per-night price by dividing total by nights
                per_night_price = stay_total_price / nights if nights > 0 else stay_total_price

                # Update per-night prices (one entry per night)
                from datetime import timedelta
                per_night_prices = {}
                total_per_night_prices = {}
                for i in range(nights):
                    night_date = (check_in_dt + timedelta(days=i)).strftime("%Y-%m-%d")
                    per_night_prices[night_date] = per_night_price
                    total_per_night_prices[night_date] = per_night_price

                template_dist["netPricePerNight"] = per_night_prices
                template_dist["totalPricePerNight"] = total_per_night_prices

                # Refundability follows the real EXT convention:
                #   refundable     -> noRefundable:false + a conditions[] cancellation
                #                     policy (stayPeriods + penalties)
                #   non-refundable -> noRefundable:true  + NO conditions key at all
                # The template ships without conditions, so we must BUILD them for
                # refundable rates (editing-in-place was a no-op → every package
                # looked refundable) and strip them for non-refundable ones.
                if refundable[index]:
                    template_dist["conditions"] = _ext_refundable_conditions(check_in, check_out)
                else:
                    template_dist.pop("conditions", None)

                accommodation["distributions"] = [template_dist]

            new_accommodations.append(accommodation)

        hotel["accommodations"] = new_accommodations

    @property
    def log_types(self) -> list[str]:
        return LOG_TYPES


def _ext_refundable_conditions(check_in: str, check_out: str) -> list[dict]:
    """A refundable EXT rate carries a cancellation policy under distributions[].
    conditions (mirrors the real supplier shape). A non-refundable rate has no
    conditions key at all; the adapter uses this presence to classify the rate.

    stayPeriods track the scenario's stay. A SINGLE penalty tier at
    daysBeforeArrival = FREE_CANCEL_DAYS_BEFORE_CHECKIN is deliberate: the adapter
    derives the cancellation `dateFrom` from the *widest* (earliest) tier, so a
    multi-tier 2/3/4 policy would anchor at check-in − 4 and diverge from HBS/EXP
    (check-in − 2). A rebooker compares these dates across suppliers and skips a
    package whose deadline differs, so all suppliers must land on the same
    free-cancel deadline."""
    return [
        {
            "stayPeriods": [{"from": check_in, "to": check_out}],
            "penalties": [
                {
                    "deductionType": "PERCENTAGE",
                    "daysBeforeArrival": FREE_CANCEL_DAYS_BEFORE_CHECKIN,
                    "deductingAmount": 100,
                },
            ],
            "isMerged": False,
        }
    ]


def _ext_packages_hotel(packages: dict) -> dict | None:
    body = packages.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return None
    body_list = body.get("body")
    if isinstance(body_list, list) and body_list and isinstance(body_list[0], dict):
        return body_list[0]
    return None


def _ext_apply_values(target: dict, values: dict) -> None:
    """Overwrite only the keys already present on the booking-flow node, and only
    with non-None source values."""
    for key, value in values.items():
        if value is not None and key in target:
            target[key] = value


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
