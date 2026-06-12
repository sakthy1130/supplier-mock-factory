"""EXP MockServer path isolation and response-body shaping."""

from __future__ import annotations

from typing import Any

EXP_CONTRACT_OPT_DEFAULTS: dict[str, Any] = {
    "enableAdapterTransformedLog": True,
}


def apply_exp_contract_opt_defaults(opt: dict[str, Any], mock_base_url: str) -> dict[str, Any]:
    """Ensure EXP contract opt has the required flags (mirrors HBS equivalent)."""
    for key, value in EXP_CONTRACT_OPT_DEFAULTS.items():
        if opt.get(key) is None:
            opt[key] = value
    return opt


EXP_MOCK_PATH_SUFFIX: dict[str, str] = {
    "Search": "search",
    "Packages": "package",
}

# PreBooking / Booking / GetOrder / CancelOrder keep canonical /v3/... template paths.


def build_exp_mock_path(namespace: str, log_type: str) -> str | None:
    suffix = EXP_MOCK_PATH_SUFFIX.get(log_type)
    if not suffix:
        return None
    safe = namespace.strip().replace(" ", "-")
    return f"/{safe}/{suffix}"


def build_exp_price_check_href(
    property_id: str,
    room_id: str,
    rate_id: str,
    token: str = "",
) -> str:
    path = f"/v3/properties/{property_id}/rooms/{room_id}/rates/{rate_id}"
    if token:
        return f"{path}?{token}" if not token.startswith("?") else f"{path}{token}"
    return path


def extract_price_check_token(href: str) -> str:
    if not isinstance(href, str) or "?" not in href:
        return ""
    return href.split("?", 1)[1]


def apply_exp_mock_path(expectation: dict[str, Any], namespace: str, log_type: str) -> dict[str, Any]:
    """Namespace paths only for Search/Packages override URLs; other log types stay on /v3/..."""
    if log_type in EXP_MOCK_PATH_SUFFIX:
        mock_path = build_exp_mock_path(namespace, log_type)
        if mock_path:
            http_request = expectation.setdefault("httpRequest", {})
            if isinstance(http_request, dict):
                http_request["path"] = mock_path
        _unwrap_adapter_log_body(expectation, log_type)
    return expectation


def _unwrap_adapter_log_body(expectation: dict[str, Any], log_type: str) -> None:
    if log_type not in {"Search", "Packages"}:
        return
    http_response = expectation.get("httpResponse")
    if not isinstance(http_response, dict):
        return
    body = http_response.get("body")
    if isinstance(body, dict) and isinstance(body.get("body"), list):
        http_response["body"] = body["body"]
