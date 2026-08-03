"""Map built expectations to MockServer contract opt URLs."""

from __future__ import annotations

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
    if supplier_code == "EXP":
        return build_exp_override_opt_urls(mock_base_url, paths_by_log_type)

    base = mock_base_url.rstrip("/")
    opt: dict[str, str] = {}
    for log_type, path in paths_by_log_type.items():
        field = LOG_TYPE_TO_OPT_FIELD.get(log_type)
        if not field or not path.startswith("/"):
            continue
        url_path = path
        if supplier_code == "HBS" and log_type == "GetOrder":
            # The HBS GetOrder mock path carries the booking id
            # (.../GetOrderBooking/<id>) so the expectation matches the request the
            # adapter actually sends. But the adapter treats the contract orderUrl
            # as a BASE and appends the id itself, so the contract must stop at
            # /GetOrderBooking — otherwise the id is doubled (.../<id>/<id>) → 404.
            url_path = _hbs_get_order_base_path(path)
        opt[field] = f"{base}{url_path}"
    _apply_opt_fallbacks(opt, base, paths_by_log_type)
    return opt


def _hbs_get_order_base_path(path: str) -> str:
    marker = "/GetOrderBooking"
    idx = path.find(marker)
    if idx != -1:
        return path[: idx + len(marker)]
    return path


def build_exp_override_opt_urls(
    mock_base_url: str,
    paths_by_log_type: dict[str, str],
) -> dict[str, str]:
    """EXP routes via override*Url fields in contract opt. But the EXP contract is
    cloned from a real Expedia reference whose standard bookingUrl/orderUrl/etc.
    point at api.ean.com — and core's E2002 "Booking url is blocked" check reads
    those standard fields, not the overrides. So set BOTH: the override*Url for
    routing AND the standard *Url pointed at the mock so the block check passes."""
    base = mock_base_url.rstrip("/")
    opt: dict[str, str] = {}
    for log_type, path in paths_by_log_type.items():
        if not path.startswith("/"):
            continue
        override_field = EXP_LOG_TYPE_TO_OVERRIDE_FIELD.get(log_type)
        if override_field:
            opt[override_field] = f"{base}{path}"
        # Also overwrite the standard field so the cloned reference's real-Expedia
        # URL (which the block check inspects) no longer points at a blocked host.
        standard_field = LOG_TYPE_TO_OPT_FIELD.get(log_type)
        if standard_field:
            opt[standard_field] = f"{base}{path}"

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
