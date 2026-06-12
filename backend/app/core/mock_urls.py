"""Map built expectations to MockServer contract opt URLs."""

from __future__ import annotations

from app.core.hbs_paths import build_hbs_contract_opt_urls
from app.core.scenario_engine import BuiltExpectation

LOG_TYPE_TO_OPT_FIELD: dict[str, str] = {
    "Search": "searchUrl",
    "Packages": "availabilityUrl",
    "CancellationPolicy": "cancellationPolicyUrl",
    "PreBooking": "prebookingUrl",
    "Booking": "bookingUrl",
    "GetOrder": "orderUrl",
    "CancelOrder": "cancelBookingUrl",
}

# EXP contracts route traffic via opt override URLs (backoffice UI labels).
EXP_LOG_TYPE_TO_OVERRIDE_FIELD: dict[str, str] = {
    "Search": "overrideSearchUrl",
    "Packages": "overridePackagesUrl",
    "Booking": "overrideBookingUrl",
    "GetOrder": "overrideRetrieveBookingUrl",
    "CancelOrder": "overrideCancelBookingUrl",
}


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
    if supplier_code == "HBS":
        return build_hbs_contract_opt_urls(mock_base_url)
    if supplier_code == "EXP":
        return build_exp_override_opt_urls(mock_base_url, paths_by_log_type)

    base = mock_base_url.rstrip("/")
    opt: dict[str, str] = {}
    for log_type, path in paths_by_log_type.items():
        field = LOG_TYPE_TO_OPT_FIELD.get(log_type)
        if not field or not path.startswith("/"):
            continue
        opt[field] = f"{base}{path}"
    _apply_opt_fallbacks(opt, base, paths_by_log_type)
    return opt


def build_exp_override_opt_urls(
    mock_base_url: str,
    paths_by_log_type: dict[str, str],
) -> dict[str, str]:
    """EXP uses override*Url fields in contract opt (not searchUrl/bookingUrl)."""
    base = mock_base_url.rstrip("/")
    opt: dict[str, str] = {}
    for log_type, path in paths_by_log_type.items():
        field = EXP_LOG_TYPE_TO_OVERRIDE_FIELD.get(log_type)
        if not field or not path.startswith("/"):
            continue
        opt[field] = f"{base}{path}"

    search = paths_by_log_type.get("Search")
    packages = paths_by_log_type.get("Packages")
    if packages and "overridePackagesUrl" not in opt:
        opt["overridePackagesUrl"] = f"{base}{packages}"
    if search and "overrideSearchUrl" not in opt:
        opt["overrideSearchUrl"] = f"{base}{search}"
    if "overrideBookingUrl" not in opt:
        booking = paths_by_log_type.get("Booking")
        if booking:
            opt["overrideBookingUrl"] = f"{base}{booking}"
    if "overrideRetrieveBookingUrl" not in opt:
        get_order = paths_by_log_type.get("GetOrder")
        if get_order:
            opt["overrideRetrieveBookingUrl"] = f"{base}{get_order}"
    if "overrideCancelBookingUrl" not in opt:
        cancel = paths_by_log_type.get("CancelOrder")
        if cancel:
            opt["overrideCancelBookingUrl"] = f"{base}{cancel}"
    return opt


def _apply_opt_fallbacks(
    opt: dict[str, str],
    base: str,
    paths_by_log_type: dict[str, str],
) -> None:
    search = paths_by_log_type.get("Search")
    packages = paths_by_log_type.get("Packages")
    fallback_availability = packages or search
    if fallback_availability:
        opt.setdefault("availabilityUrl", f"{base}{fallback_availability}")
        opt.setdefault("searchUrl", f"{base}{search or packages or fallback_availability}")
    for field in (
        "cancellationPolicyUrl",
        "cancellationUrl",
        "statusUrl",
        "prebookingUrl",
        "orderUrl",
        "bookingUrl",
        "cancelBookingUrl",
    ):
        opt.setdefault(field, opt.get("bookingUrl") or opt.get("orderUrl") or opt.get("searchUrl", base))
