"""Helpers for MockServer expectation shaping."""

from __future__ import annotations

from typing import Any

from app.core.exp_paths import apply_exp_mock_path
from app.core.hbs_paths import apply_hbs_mock_path
from app.core.namespace import apply_namespace, safe_namespace_path_segment


def strip_http_request_matchers(expectation: dict[str, Any]) -> dict[str, Any]:
    """Remove httpRequest body/header matchers — match path + method only."""
    http_request = expectation.get("httpRequest")
    if isinstance(http_request, dict):
        http_request.pop("body", None)
        http_request.pop("headers", None)
    return expectation


# Body-framing headers captured verbatim from the real supplier response. Once the
# mock body is mutated (prices, room names) or served uncompressed, these become
# invalid: a stale Content-Length makes the client wait for bytes that never arrive
# and Content-Encoding: gzip makes it try to gunzip plain JSON — the socket hangs
# until the adapter's read timeout fires (EXP → E1011.1 "could not parse"). Let
# MockServer recompute framing instead of replaying the recorded values.
_FRAMING_RESPONSE_HEADERS = {
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "connection",
}


def strip_response_framing_headers(expectation: dict[str, Any]) -> dict[str, Any]:
    """Drop stale body-framing headers from httpResponse (Content-Length, gzip, etc.)."""
    http_response = expectation.get("httpResponse")
    if isinstance(http_response, dict):
        headers = http_response.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if key.lower() in _FRAMING_RESPONSE_HEADERS:
                    headers.pop(key, None)
    return expectation


def apply_namespace_path_prefix(expectation: dict[str, Any], namespace: str) -> dict[str, Any]:
    """Prefix httpRequest.path with the namespace so every supplier's mock path is
    unique per scenario, e.g. /hotel-api/1.0/hotels/search -> /{namespace}/hotel-api/1.0/hotels/search.
    """
    http_request = expectation.get("httpRequest")
    if isinstance(http_request, dict):
        path = http_request.get("path")
        if isinstance(path, str) and path:
            safe = safe_namespace_path_segment(namespace)
            http_request["path"] = f"/{safe}/{path.lstrip('/')}"
    return expectation


def finalize_expectation_for_register(
    expectation: dict[str, Any],
    namespace: str,
    supplier_code: str,
    log_type: str,
) -> dict[str, Any]:
    """Apply namespace id, prefix the path with the namespace, and strip request
    body/header matchers before MockServer register."""
    apply_namespace(expectation, namespace, supplier_code, log_type)
    if supplier_code == "HBS":
        apply_hbs_mock_path(expectation, log_type)
    elif supplier_code == "EXP":
        apply_exp_mock_path(expectation, log_type)
    apply_namespace_path_prefix(expectation, namespace)
    strip_response_framing_headers(expectation)
    return strip_http_request_matchers(expectation)


# Backward-compatible alias used in earlier tests/imports.
strip_http_request_body = strip_http_request_matchers
