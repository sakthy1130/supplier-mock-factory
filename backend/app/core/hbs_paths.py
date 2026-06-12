"""Canonical HBS contract paths and MockServer path suffixes."""

from __future__ import annotations

from typing import Any

# Real Hotelbeds API path roots (v1.0 search/packages, v1.0 prebook, v1.2 booking flow).
HBS_CANONICAL_BASE: dict[str, str] = {
    "Search": "/hotel-api/1.0/hotels",
    "Packages": "/hotel-api/1.0/hotels",
    "PreBooking": "/hotel-api/1.0/checkrates",
    "Booking": "/hotel-api/1.2/bookings",
    "GetOrder": "/hotel-api/1.2/bookings",
    "CancelOrder": "/hotel-api/1.2/bookings",
}

# Disambiguate mocks on shared paths (MockServer matches path + method only).
HBS_MOCK_PATH_SUFFIX: dict[str, str] = {
    "Search": "search",
    "Packages": "package/availability",
    "PreBooking": "preBooking",
    "Booking": "booking",
    "GetOrder": "GetOrderBooking",
    "CancelOrder": "cancelBooking",
}

HBS_LOG_TYPE_TO_OPT_FIELD: dict[str, str] = {
    "Search": "searchUrl",
    "Packages": "availabilityUrl",
    "PreBooking": "prebookingUrl",
    "Booking": "bookingUrl",
    "GetOrder": "orderUrl",
    "CancelOrder": "cancelBookingUrl",
}


def build_hbs_mock_path(log_type: str) -> str | None:
    base = HBS_CANONICAL_BASE.get(log_type)
    suffix = HBS_MOCK_PATH_SUFFIX.get(log_type)
    if not base or not suffix:
        return None
    return f"{base}/{suffix}"


def apply_hbs_mock_path(expectation: dict[str, Any], log_type: str) -> dict[str, Any]:
    """Set httpRequest.path to canonical HBS base + log-type suffix."""
    mock_path = build_hbs_mock_path(log_type)
    if not mock_path:
        return expectation
    http_request = expectation.setdefault("httpRequest", {})
    if isinstance(http_request, dict):
        http_request["path"] = mock_path
    return expectation


# Required opt fields for HBS adapter — missing availabilityTimeoutSeconds causes 0ms timeout.
# Boolean/numeric flags must be real JSON types (not "true"/"false" strings) or adapter throws ClassCastException.
HBS_CONTRACT_OPT_DEFAULTS: dict[str, Any] = {
    "availabilityTimeoutSeconds": "50",
    "cancellationPoliciesTimeoutSeconds": "10",
    "paymentType": "AT_WEB",
    "packagingEnabled": False,
    "enableAdapterTransformedLog": True,
    "bufferCancellationPoliciesInDays": 0,
    "isRetryCancellationPolicyDisabled": False,
    "flowWithoutCPEnabled": True,
    "filterUnnecessaryPackages": False,
    "multiroomEnabled": True,
    "enableMultiTypeRooms": True,
    "useCostToCeilCP": True,
    "prebookingMaximumCPChangePercentage": 0,
    "supplierSubType": 1,
}


def apply_hbs_contract_opt_defaults(opt: dict[str, Any], mock_base_url: str) -> dict[str, Any]:
    """Ensure HBS contract opt has adapter-required timeouts and flags."""
    for key, value in HBS_CONTRACT_OPT_DEFAULTS.items():
        current = opt.get(key)
        if current is None or str(current).strip() in ("", "0"):
            opt[key] = value
    # Always enforce packages timeout — cloned reference contracts may carry "0".
    opt["availabilityTimeoutSeconds"] = HBS_CONTRACT_OPT_DEFAULTS["availabilityTimeoutSeconds"]
    opt["cancellationPoliciesTimeoutSeconds"] = HBS_CONTRACT_OPT_DEFAULTS[
        "cancellationPoliciesTimeoutSeconds"
    ]
    opt["mockServerUrl"] = f"{mock_base_url.rstrip('/')}/"
    return opt


def build_hbs_contract_opt_urls(mock_base_url: str) -> dict[str, str]:
    """HBS contract opt URLs on MockServer — canonical roots + disambiguation suffix."""
    base = mock_base_url.rstrip("/")
    opt: dict[str, str] = {}
    for log_type, field in HBS_LOG_TYPE_TO_OPT_FIELD.items():
        mock_path = build_hbs_mock_path(log_type)
        if mock_path:
            opt[field] = f"{base}{mock_path}"
    apply_hbs_contract_opt_defaults(opt, mock_base_url)
    return opt
