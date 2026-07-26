"""Canonical EXT (Extranet) contract paths and MockServer path suffixes."""

from __future__ import annotations

from typing import Any

# Extranet API path roots (all under /extranet/public/api/v1/).
EXT_CANONICAL_BASE: dict[str, str] = {
    "Search": "/extranet/public/api/v1/distribution",
    "Packages": "/extranet/public/api/v1/distribution",
    "Booking": "/extranet/public/api/v1/accommodation",
    "GetOrder": "/extranet/public/api/v1/accommodation",
    "CancelOrder": "/extranet/public/api/v1/accommodation",
}

# Disambiguate mocks on shared paths (MockServer matches path + method only).
EXT_MOCK_PATH_SUFFIX: dict[str, str] = {
    "Search": "search",
    "Packages": "details",
    "Booking": "confirm",
    "GetOrder": "search",
    "CancelOrder": "cancel",
}

EXT_LOG_TYPE_TO_OPT_FIELD: dict[str, str] = {
    "Search": "searchUrl",
    "Packages": "availabilityUrl",
    "Booking": "bookingUrl",
    "GetOrder": "orderUrl",
    "CancelOrder": "cancelBookingUrl",
}


def build_ext_mock_path(log_type: str) -> str | None:
    base = EXT_CANONICAL_BASE.get(log_type)
    suffix = EXT_MOCK_PATH_SUFFIX.get(log_type)
    if not base or not suffix:
        return None
    return f"{base}/{suffix}"


def apply_ext_mock_path(expectation: dict[str, Any], log_type: str) -> dict[str, Any]:
    """Set httpRequest.path to canonical EXT base + log-type suffix."""
    mock_path = build_ext_mock_path(log_type)
    if not mock_path:
        return expectation
    http_request = expectation.setdefault("httpRequest", {})
    if isinstance(http_request, dict):
        http_request["path"] = mock_path
    return expectation


# Required opt fields for EXT adapter (NET supplier like HBS).
EXT_CONTRACT_OPT_DEFAULTS: dict[str, Any] = {
    "availabilityTimeoutSeconds": "7",
    "cancellationPoliciesTimeoutSeconds": "10",
    "paymentType": "AT_WEB",
    "packagingEnabled": False,
    "enableAdapterTransformedLog": True,
    "bufferCancellationPoliciesInDays": 0,
    "isRetryCancellationPolicyDisabled": False,
    "filterUnnecessaryPackages": False,
    "supplierSubType": 2,
}


def apply_ext_contract_opt_defaults(opt: dict[str, Any], mock_base_url: str) -> dict[str, Any]:
    """Ensure EXT contract opt has adapter-required timeouts and flags."""
    for key, value in EXT_CONTRACT_OPT_DEFAULTS.items():
        current = opt.get(key)
        if current is None or str(current).strip() in ("", "0"):
            opt[key] = value
    # Always enforce packages timeout.
    opt["availabilityTimeoutSeconds"] = EXT_CONTRACT_OPT_DEFAULTS["availabilityTimeoutSeconds"]
    opt["cancellationPoliciesTimeoutSeconds"] = EXT_CONTRACT_OPT_DEFAULTS[
        "cancellationPoliciesTimeoutSeconds"
    ]
    opt["mockServerUrl"] = f"{mock_base_url.rstrip('/')}/"
    return opt


def build_ext_contract_opt_urls(mock_base_url: str) -> dict[str, str]:
    """EXT contract opt URLs on MockServer — canonical roots + disambiguation suffix."""
    base = mock_base_url.rstrip("/")
    opt: dict[str, str] = {}
    for log_type, field in EXT_LOG_TYPE_TO_OPT_FIELD.items():
        mock_path = build_ext_mock_path(log_type)
        if mock_path:
            opt[field] = f"{base}{mock_path}"
    apply_ext_contract_opt_defaults(opt, mock_base_url)
    return opt
