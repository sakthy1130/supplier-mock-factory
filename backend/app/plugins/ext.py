"""EXT (Extranet) supplier plugin. NET supplier with distribution-based pricing."""

from __future__ import annotations

import uuid

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

        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        """Propagate searchId and accommodation data across log types."""
        # EXT doesn't require explicit linkage synchronization in the same way
        # as HBS/CHC — the structure is more flexible
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

            # Update price fields
            price = prices[index]
            accommodation["initialPrice"] = price * nights
            accommodation["totalPrice"] = price * nights
            accommodation["netPrice"] = price * nights
            accommodation["noRefundable"] = not refundable[index]

            # Update distributions (rooms in EXT terminology)
            distributions = accommodation.get("distributions", [])
            if isinstance(distributions, list) and distributions:
                template_dist = deep_copy(distributions[0])
                template_dist["board"] = meals[index]

                # Update price details
                price_details = template_dist.get("priceDetails", {})
                if isinstance(price_details, dict):
                    price_details["initialPrice"] = price * nights
                    price_details["netPrice"] = price * nights
                    price_details["totalPrice"] = price * nights

                # Update per-night prices
                per_night_prices = {}
                total_per_night_prices = {}
                for i in range(nights):
                    night_date = (check_in_dt.replace(day=check_in_dt.day + i)).strftime("%Y-%m-%d") if i == 0 else (check_in_dt + __import__('datetime').timedelta(days=i)).strftime("%Y-%m-%d")
                    per_night_prices[night_date] = price
                    total_per_night_prices[night_date] = price

                template_dist["netPricePerNight"] = per_night_prices
                template_dist["totalPricePerNight"] = total_per_night_prices

                accommodation["distributions"] = [template_dist]

            new_accommodations.append(accommodation)

        hotel["accommodations"] = new_accommodations

    @property
    def log_types(self) -> list[str]:
        return LOG_TYPES


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
