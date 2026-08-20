"""Generate and inject bookingIds into book/getOrder/cancel."""

from __future__ import annotations

import secrets
import string

from app.core.path_utils import get_by_path, replace_string_values, set_by_path
from app.models.supplier import MutationConfig

BOOKING_FLOW_LOG_TYPES = frozenset({"Booking", "GetOrder", "CancelOrder"})


def _mutation_config(supplier_code: str) -> MutationConfig:
    """The supplier's booking-id rules; empty config for an unconfigured code."""
    from app.services.supplier_service import UnknownSupplierError, get_supplier_config

    try:
        return get_supplier_config(supplier_code).mutation_config
    except UnknownSupplierError:
        return MutationConfig()


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

        # Configured fallbacks, for templates whose field map missed the id
        # (e.g. a nested reservations[0].bookingId that no key search reached).
        for path in _mutation_config(supplier_code).booking_id_fallback_paths:
            try:
                value = get_by_path(booking_expectation, path)
            except (KeyError, TypeError, IndexError):
                continue
            if value is not None and str(value).strip():
                return str(value).strip()

        raise ValueError(f"Could not extract booking id for supplier {supplier_code}")

    def generate_booking_id(self, supplier_code: str, sample_id: str) -> str:
        """A fresh id in the same shape as the template's, per the supplier's format."""
        booking_id_format = _mutation_config(supplier_code).booking_id_format

        if booking_id_format == "prefix_digits" and "-" in sample_id:
            prefix, suffix = sample_id.split("-", 1)
            width = max(len(suffix), 7)
            generated_suffix = "".join(secrets.choice(string.digits) for _ in range(width))
            return f"{prefix}-{generated_suffix}"

        if booking_id_format == "prefix_hex" and sample_id:
            prefix = sample_id.split("-", 1)[0] if "-" in sample_id else "smf"
            suffix = secrets.token_hex(16)
            return f"{prefix}-{suffix}"

        width = len(sample_id) if sample_id else 13
        return "".join(secrets.choice(string.digits) for _ in range(width))

    def _booking_id_paths(self, supplier_code: str, log_type: str, field_map: dict) -> list[str]:
        # Some suppliers carry the id somewhere different in each log type (RHK's
        # Booking response has a null body.data), so a per-log-type override wins
        # over the field map's flat list of paths.
        per_log_type = _mutation_config(supplier_code).booking_id_paths_by_log_type
        if per_log_type:
            return per_log_type.get(log_type, [])
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
        if log_type == "GetOrder":
            self._apply_get_order_path(expectation, supplier_code, new_id)

    @staticmethod
    def _apply_get_order_path(expectation: dict, supplier_code: str, booking_id: str) -> None:
        """Retarget a GetOrder mock whose path carries the booking id (<base>/<id>)."""
        from app.services.supplier_service import UnknownSupplierError, get_supplier_config

        try:
            mock_config = get_supplier_config(supplier_code).mock_config
        except UnknownSupplierError:
            return
        if not mock_config.booking_id_in_get_order_path:
            return

        base = mock_config.mock_path("GetOrder")
        if not base:
            return

        http_request = expectation.get("httpRequest")
        if not isinstance(http_request, dict):
            return
        path = http_request.get("path")
        if not isinstance(path, str) or not path:
            return

        suffix = mock_config.mock_path_suffix.get("GetOrder", "")
        if path == base or (suffix and path.endswith(f"/{suffix}")) or path.startswith(f"{base}/"):
            http_request["path"] = f"{base}/{booking_id}"
