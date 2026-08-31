"""Helpers for MockServer expectation shaping."""

from __future__ import annotations

from typing import Any

from app.core.exp_paths import apply_exp_mock_path, apply_namespace_to_price_check_hrefs
from app.core.hbs_paths import apply_hbs_mock_path
from app.core.namespace import (
    apply_namespace,
    instance_path_segment,
    safe_namespace_path_segment,
)
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
    log_type: str,
) -> dict[str, Any]:
    """Move a registry supplier's mock off the path its template captured.

    Scenario isolation is no longer this function's job — ``apply_namespace_path_prefix``
    prefixes every supplier's path with /{namespace} regardless. What is left is the one
    thing the prefix cannot do: separate two log types that share a single path. Derby
    availability and prebook are both POSTs to .../availability, and MockServer matches
    on path + method only, so without a distinct suffix one expectation answers both.

    ``path_rewrite`` pins the mock onto the supplier's canonical base plus the log
    type's suffix — the config-driven equivalent of what hbs_paths does in code. A
    supplier with suffixes but no canonical base (Derby) just gets ``/{suffix}``, which
    is enough to keep its log types apart. Paths here are namespace-free; the prefixer
    runs after.
    """
    mock_path = mock_config.mock_path(log_type) if mock_config.path_rewrite else None
    if mock_path is None:
        suffix = mock_config.mock_path_suffix.get(log_type)
        mock_path = f"/{suffix.lstrip('/')}" if suffix else None

    if mock_path:
        http_request = expectation.setdefault("httpRequest", {})
        if isinstance(http_request, dict):
            http_request["path"] = mock_path
    return expectation


def _unwrap_adapter_log_body(expectation: dict[str, Any]) -> None:
    """Strip the adapter-log envelope: {"body": [...]} -> [...]."""
    http_response = expectation.get("httpResponse")
    if not isinstance(http_response, dict):
        return
    body = http_response.get("body")
    if isinstance(body, dict) and isinstance(body.get("body"), list):
        http_response["body"] = body["body"]


def build_path_prefix(namespace: str, instance_segment: str = "") -> str:
    """Leading path segments for a scenario's mocks: /{namespace}, plus an instance
    segment when the same supplier appears more than once."""
    prefix = f"/{safe_namespace_path_segment(namespace)}"
    if instance_segment:
        prefix = f"{prefix}/{instance_segment}"
    return prefix


def apply_namespace_path_prefix(
    expectation: dict[str, Any],
    namespace: str,
    instance_segment: str = "",
) -> dict[str, Any]:
    """Prefix httpRequest.path with the namespace so every supplier's mock path is
    unique per scenario, e.g. /hotel-api/1.0/hotels/search -> /{namespace}/hotel-api/1.0/hotels/search.
    A repeated supplier also gets its instance segment: /{namespace}/exp-2/... .
    """
    http_request = expectation.get("httpRequest")
    if isinstance(http_request, dict):
        path = http_request.get("path")
        if isinstance(path, str) and path:
            prefix = build_path_prefix(namespace, instance_segment)
            http_request["path"] = f"{prefix}/{path.lstrip('/')}"
    return expectation


def finalize_expectation_for_register(
    expectation: dict[str, Any],
    namespace: str,
    supplier_code: str,
    log_type: str,
    instance_key: str = "",
) -> dict[str, Any]:
    """Apply namespace id, prefix the path with the namespace, and strip request
    body/header matchers before MockServer register.

    `instance_key` distinguishes repeated entries of one supplier code; it defaults
    to the code itself, which is the single-instance behaviour.

    HBS and EXP have path quirks expressed in code (hbs_paths, exp_paths). Every other
    supplier is shaped from its registry mock_config, so a supplier added from the
    Suppliers screen gets the same treatment without a branch here.
    """
    from app.services.supplier_service import UnknownSupplierError, get_supplier_config

    instance_key = instance_key or supplier_code
    instance_segment = instance_path_segment(supplier_code, instance_key)
    apply_namespace(expectation, namespace, instance_key, log_type)
    if supplier_code == "HBS":
        apply_hbs_mock_path(expectation, log_type)
    elif supplier_code == "EXP":
        apply_exp_mock_path(expectation, log_type)
        # The price_check href lives in the response BODY, which the path prefixer
        # below never touches — namespace it here or the adapter calls the
        # unprefixed /v3/properties/... and misses the PreBooking mock. It must use
        # the SAME prefix as the path below, instance segment included, or two EXP
        # entries would both point at the first one's price-check mock.
        apply_namespace_to_price_check_hrefs(
            expectation, build_path_prefix(namespace, instance_segment)
        )
    else:
        try:
            mock_config = get_supplier_config(supplier_code).mock_config
        except UnknownSupplierError:
            # Nothing to shape for an unconfigured code; the engine reports it upstream.
            mock_config = MockConfig()
        apply_mock_path(expectation, mock_config, log_type)
        if mock_config.unwrap_adapter_log_body:
            _unwrap_adapter_log_body(expectation)
    apply_namespace_path_prefix(expectation, namespace, instance_segment)
    strip_response_framing_headers(expectation)
    return strip_http_request_matchers(expectation)


# Backward-compatible alias used in earlier tests/imports.
strip_http_request_body = strip_http_request_matchers
