"""Map built expectations to MockServer contract opt URLs."""

from __future__ import annotations

from app.core.contract_opt import apply_contract_opt_defaults
from app.core.opt_fields import (
    EXP_LOG_TYPE_TO_OVERRIDE_FIELD,
    LOG_TYPE_TO_OPT_FIELD,
    OPT_FALLBACK_FIELDS,
)
from app.core.scenario_engine import BuiltExpectation
from app.models.supplier import MockConfig
from app.services.supplier_service import get_supplier_config

# Re-exported for the seed and for callers that imported them from here.
__all__ = [
    "EXP_LOG_TYPE_TO_OVERRIDE_FIELD",
    "LOG_TYPE_TO_OPT_FIELD",
    "build_exp_override_opt_urls",
    "build_mock_opt_urls",
    "extract_paths_from_built",
]


def extract_paths_from_built(built: list[BuiltExpectation]) -> dict[str, dict[str, str]]:
    paths: dict[str, dict[str, str]] = {}
    for item in built:
        http_path = item.expectation.get("httpRequest", {}).get("path")
        if isinstance(http_path, str) and http_path:
            paths.setdefault(item.supplier_code, {})[item.log_type] = http_path
    return paths


def build_mock_opt_urls(
    mock_base_url: str,
    paths_by_log_type: dict[str, str],
    supplier_code: str | None = None,
) -> dict[str, str]:
    """Contract opt URLs for one supplier.

    ``opt_source: "canonical"`` builds the URLs from the supplier's canonical API paths
    and ignores what the templates carry (HBS — its mocks are always registered on the
    canonical paths). Everyone else maps the paths the built expectations actually have
    onto the supplier's opt field names.
    """
    if supplier_code is None:
        return _build_from_paths(mock_base_url, paths_by_log_type, MockConfig())

    config = get_supplier_config(supplier_code)
    mock_config = config.mock_config
    if mock_config.opt_source == "canonical":
        return _build_from_canonical(mock_base_url, mock_config)
    return _build_from_paths(mock_base_url, paths_by_log_type, mock_config)


def build_exp_override_opt_urls(
    mock_base_url: str,
    paths_by_log_type: dict[str, str],
) -> dict[str, str]:
    """EXP uses override*Url fields in contract opt (not searchUrl/bookingUrl).

    Kept as a named helper because it is the one field map whose names sit outside the
    generic set; it now just calls the shared builder with EXP's map.
    """
    return _build_from_paths(
        mock_base_url,
        paths_by_log_type,
        MockConfig(opt_field_map=EXP_LOG_TYPE_TO_OVERRIDE_FIELD),
    )


def _build_from_canonical(mock_base_url: str, mock_config: MockConfig) -> dict[str, str]:
    base = mock_base_url.rstrip("/")
    opt: dict[str, str] = {}
    for log_type, field in mock_config.opt_field_map.items():
        mock_path = mock_config.mock_path(log_type)
        if mock_path:
            opt[field] = f"{base}{mock_path}"
    apply_contract_opt_defaults(opt, mock_config, mock_base_url)
    return opt


def _build_from_paths(
    mock_base_url: str,
    paths_by_log_type: dict[str, str],
    mock_config: MockConfig,
) -> dict[str, str]:
    base = mock_base_url.rstrip("/")
    field_map = mock_config.opt_field_map or LOG_TYPE_TO_OPT_FIELD
    opt: dict[str, str] = {}
    for log_type, path in paths_by_log_type.items():
        field = field_map.get(log_type)
        if not field or not path.startswith("/"):
            continue
        opt[field] = f"{base}{path}"

    # EXP names its fields override*Url and needs Search/Packages present even when the
    # per-log-type loop missed them; the generic path needs availability/search plus a
    # sensible fallback for every remaining field. Both are the same shape, keyed off
    # whichever field names this supplier uses.
    _apply_opt_fallbacks(opt, base, paths_by_log_type, field_map)
    return opt


def _apply_opt_fallbacks(
    opt: dict[str, str],
    base: str,
    paths_by_log_type: dict[str, str],
    field_map: dict[str, str],
) -> None:
    search = paths_by_log_type.get("Search")
    packages = paths_by_log_type.get("Packages")
    fallback_availability = packages or search

    availability_field = field_map.get("Packages")
    search_field = field_map.get("Search")
    if fallback_availability and availability_field:
        opt.setdefault(availability_field, f"{base}{fallback_availability}")
    if search_field:
        resolved_search = search or packages or fallback_availability
        if resolved_search:
            opt.setdefault(search_field, f"{base}{resolved_search}")

    # Booking-flow fields the supplier declares but whose templates were absent.
    for log_type in ("Booking", "GetOrder", "CancelOrder"):
        field = field_map.get(log_type)
        path = paths_by_log_type.get(log_type)
        if field and path:
            opt.setdefault(field, f"{base}{path}")

    # Only the generic (non-override) field names get the blanket fallback — EXP's
    # override fields must stay absent rather than point at the wrong endpoint.
    if field_map is not LOG_TYPE_TO_OPT_FIELD and set(field_map.values()) - set(
        LOG_TYPE_TO_OPT_FIELD.values()
    ):
        return
    for field in OPT_FALLBACK_FIELDS:
        opt.setdefault(
            field, opt.get("bookingUrl") or opt.get("orderUrl") or opt.get("searchUrl", base)
        )
