"""Generate and inject bookingIds into book/getOrder/cancel."""

from __future__ import annotations

import secrets
import string

from app.core.path_utils import get_by_path, replace_string_values, set_by_path

BOOKING_FLOW_LOG_TYPES = frozenset({"Booking", "GetOrder", "CancelOrder"})

# RHK templates differ per log type (Booking body.data is null).
RHK_BOOKING_ID_PATHS: dict[str, list[str]] = {
    "Booking": [
        "httpResponse.body.debug.request.partner.partner_order_id",
    ],
    "GetOrder": [
        "httpResponse.body.data.orders[0].order_id",
        "httpResponse.body.data.orders[0].supplier_data.order_id",
        "httpResponse.body.data.orders[0].partner_data.order_id",
    ],
    "CancelOrder": [
        "httpResponse.body.debug.request.partner_order_id",
    ],
}


class BookingIdInjector:
    @staticmethod
    def generate_id(length: int = 22, alphabet: str | None = None) -> str:
        chars = alphabet or (string.ascii_uppercase + string.digits)
        return "".join(secrets.choice(chars) for _ in range(length))

    def inject(
        self,
        expectations_by_type: dict[str, dict],
        supplier_code: str,
        field_map: dict,
        booking_id: str | None = None,
    ) -> str:
        booking = expectations_by_type.get("Booking")
        if booking is None:
            raise ValueError(f"{supplier_code} Booking expectation required for booking id injection")

        current_id = self.extract_booking_id(booking, supplier_code, field_map)
        new_id = booking_id or self.generate_booking_id(supplier_code, current_id)

        for log_type in BOOKING_FLOW_LOG_TYPES:
            expectation = expectations_by_type.get(log_type)
            if expectation is None:
                continue
            self._apply_booking_id(expectation, field_map, current_id, new_id, supplier_code, log_type)

        return new_id

    def extract_booking_id(
        self,
        booking_expectation: dict,
        supplier_code: str,
        field_map: dict,
    ) -> str:
        for path in field_map.get("paths", {}).get("booking_id", []):
            try:
                value = get_by_path(booking_expectation, path)
            except KeyError:
                continue
            if value is not None and str(value).strip():
                return str(value).strip()

        if supplier_code == "HBS":
            reference = (
                booking_expectation.get("httpResponse", {})
                .get("body", {})
                .get("booking", {})
                .get("reference")
            )
            if reference:
                return str(reference)
        if supplier_code == "EXP":
            itinerary_id = (
                booking_expectation.get("httpResponse", {}).get("body", {}).get("itinerary_id")
            )
            if itinerary_id:
                return str(itinerary_id)
        if supplier_code == "RHK":
            partner_order_id = (
                booking_expectation.get("httpResponse", {})
                .get("body", {})
                .get("debug", {})
                .get("request", {})
                .get("partner", {})
                .get("partner_order_id")
            )
            if partner_order_id:
                return str(partner_order_id)

        raise ValueError(f"Could not extract booking id for supplier {supplier_code}")

    def generate_booking_id(self, supplier_code: str, sample_id: str) -> str:
        if supplier_code == "HBS" and "-" in sample_id:
            prefix, suffix = sample_id.split("-", 1)
            width = max(len(suffix), 7)
            generated_suffix = "".join(secrets.choice(string.digits) for _ in range(width))
            return f"{prefix}-{generated_suffix}"

        if supplier_code == "RHK" and sample_id:
            prefix = sample_id.split("-", 1)[0] if "-" in sample_id else "smf"
            suffix = secrets.token_hex(16)
            return f"{prefix}-{suffix}"

        width = len(sample_id) if sample_id else 13
        return "".join(secrets.choice(string.digits) for _ in range(width))

    def _booking_id_paths(self, supplier_code: str, log_type: str, field_map: dict) -> list[str]:
        if supplier_code == "RHK":
            return RHK_BOOKING_ID_PATHS.get(log_type, [])
        return field_map.get("paths", {}).get("booking_id", [])

    def _apply_booking_id(
        self,
        expectation: dict,
        field_map: dict,
        old_id: str,
        new_id: str,
        supplier_code: str,
        log_type: str,
    ) -> None:
        for path in self._booking_id_paths(supplier_code, log_type, field_map):
            try:
                set_by_path(expectation, path, new_id)
            except (KeyError, TypeError, IndexError):
                continue
        replace_string_values(expectation, old_id, new_id)
        if supplier_code == "HBS" and log_type == "GetOrder":
            self._apply_hbs_get_order_path(expectation, new_id)

    @staticmethod
    def _apply_hbs_get_order_path(expectation: dict, booking_id: str) -> None:
        http_request = expectation.get("httpRequest")
        if not isinstance(http_request, dict):
            return

        path = http_request.get("path")
        if not isinstance(path, str) or not path:
            return

        base = "/hotel-api/1.2/bookings/GetOrderBooking"
        if path == base or path.endswith("/GetOrderBooking"):
            http_request["path"] = f"{base}/{booking_id}"
            return

        if path.startswith(base + "/"):
            http_request["path"] = f"{base}/{booking_id}"
