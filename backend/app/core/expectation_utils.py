"""Helpers for MockServer expectation shaping."""

from __future__ import annotations

from typing import Any

from app.core.namespace import apply_namespace
from app.models.supplier import MockConfig


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


def apply_mock_path(
    expectation: dict[str, Any],
    mock_config: MockConfig,
    namespace: str,
    log_type: str,
) -> dict[str, Any]:
    """Rewrite httpRequest.path according to the supplier's path strategy.

    ``path_rewrite`` pins the mock onto the supplier's canonical API path plus a
    per-log-type suffix (HBS — MockServer matches path + method only, so log types
    sharing a path need disambiguating). ``path_namespaced`` instead isolates the mock
    per scenario on /{namespace}/<suffix>, which is how EXP's override URLs work; only
    the log types that have a suffix are moved, the rest keep their canonical paths.
    """
    mock_path: str | None = None
    if mock_config.path_namespaced:
        suffix = mock_config.mock_path_suffix.get(log_type)
        if suffix:
            safe = namespace.strip().replace(" ", "-")
            mock_path = f"/{safe}/{suffix}"
    elif mock_config.path_rewrite:
        mock_path = mock_config.mock_path(log_type)

    if mock_path:
        http_request = expectation.setdefault("httpRequest", {})
        if isinstance(http_request, dict):
            http_request["path"] = mock_path
        if mock_config.unwrap_adapter_log_body:
            _unwrap_adapter_log_body(expectation)
    return expectation


def _unwrap_adapter_log_body(expectation: dict[str, Any]) -> None:
    """Strip the adapter-log envelope: {"body": [...]} -> [...]."""
    http_response = expectation.get("httpResponse")
    if not isinstance(http_response, dict):
        return
    body = http_response.get("body")
    if isinstance(body, dict) and isinstance(body.get("body"), list):
        http_response["body"] = body["body"]


def finalize_expectation_for_register(
    expectation: dict[str, Any],
    namespace: str,
    supplier_code: str,
    log_type: str,
) -> dict[str, Any]:
    """Apply namespace id and strip request body/header matchers before MockServer register."""
    from app.services.supplier_service import UnknownSupplierError, get_supplier_config

    apply_namespace(expectation, namespace, supplier_code, log_type)
    try:
        mock_config = get_supplier_config(supplier_code).mock_config
    except UnknownSupplierError:
        # Nothing to rewrite for an unconfigured code; the engine reports it upstream.
        mock_config = MockConfig()
    apply_mock_path(expectation, mock_config, namespace, log_type)
    strip_response_framing_headers(expectation)
    return strip_http_request_matchers(expectation)


# Backward-compatible alias used in earlier tests/imports.
strip_http_request_body = strip_http_request_matchers
