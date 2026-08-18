"""EXP MockServer path isolation and response-body shaping."""

from __future__ import annotations

from typing import Any

from app.core.namespace import safe_namespace_path_segment

EXP_CONTRACT_OPT_DEFAULTS: dict[str, Any] = {
    "enableAdapterTransformedLog": True,
}


def apply_exp_contract_opt_defaults(opt: dict[str, Any], mock_base_url: str) -> dict[str, Any]:
    """Ensure EXP contract opt has the required flags (mirrors HBS equivalent)."""
    for key, value in EXP_CONTRACT_OPT_DEFAULTS.items():
        if opt.get(key) is None:
            opt[key] = value
    # Always force off — some reference contracts (e.g. a dev clone source) carry
    # enableGenericBedding: true, which makes the real EXP adapter emit a second,
    # not-for-sale "generic bedding" package per rate (room name loses the mock's
    # room_name and gets a ", <n> Bed" suffix instead). SMF mocks should produce
    # exactly the requested room_names/count with nothing extra, regardless of
    # what the cloned reference contract carried.
    opt["enableGenericBedding"] = False
    return opt


EXP_MOCK_PATH_SUFFIX: dict[str, str] = {
    "Search": "search",
    "Packages": "package",
}

# PreBooking / Booking / GetOrder / CancelOrder keep canonical /v3/... template paths.


def build_exp_mock_path(log_type: str) -> str | None:
    suffix = EXP_MOCK_PATH_SUFFIX.get(log_type)
    if not suffix:
        return None
    return f"/{suffix}"


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


def apply_exp_mock_path(expectation: dict[str, Any], log_type: str) -> dict[str, Any]:
    """Override the recorded path for Search/Packages; other log types stay on /v3/...
    (namespace prefixing is applied uniformly afterwards in expectation_utils)."""
    if log_type in EXP_MOCK_PATH_SUFFIX:
        mock_path = build_exp_mock_path(log_type)
        if mock_path:
            http_request = expectation.setdefault("httpRequest", {})
            if isinstance(http_request, dict):
                http_request["path"] = mock_path
        _unwrap_adapter_log_body(expectation, log_type)
    return expectation


PRICE_CHECK_CANONICAL_PREFIX = "/v3/properties/"


def apply_namespace_to_price_check_hrefs(
    expectation: dict[str, Any],
    path_prefix: str,
) -> dict[str, Any]:
    """Prefix every ``links.price_check.href`` in the response body with `path_prefix`.

    `path_prefix` is the same leading segment(s) the mock path gets — ``/{namespace}``,
    plus an instance segment when the supplier appears twice in one scenario. Pass a
    bare namespace and it is treated as that single segment.

    The EXP adapter reaches price-check by following the href embedded in the
    Search/Packages response, not via a contract URL. ``apply_namespace_path_prefix``
    only rewrites ``httpRequest.path``, so without this the adapter calls the
    canonical ``/v3/properties/...`` while the PreBooking mock is registered at
    ``/{namespace}/v3/properties/...`` — MockServer finds no match and the booking
    never gets past price-check.

    Idempotent: an already-prefixed href no longer starts with ``/v3/properties/``.
    """
    prefix = _normalized_prefix(path_prefix)
    if not prefix:
        return expectation
    http_response = expectation.get("httpResponse")
    if not isinstance(http_response, dict):
        return expectation
    for node in _walk_nodes(http_response.get("body")):
        if not isinstance(node, dict):
            continue
        _prefix_price_check(node.get("links"), prefix)
        bed_groups = node.get("bed_groups")
        if isinstance(bed_groups, dict):
            for bed_group in bed_groups.values():
                if isinstance(bed_group, dict):
                    _prefix_price_check(bed_group.get("links"), prefix)
    return expectation


def _normalized_prefix(path_prefix: str) -> str:
    """Accept either a leading-slash path prefix ("/ns/exp-2") or a bare namespace
    ("ns"), and return it as a clean "/a/b" with no trailing slash."""
    raw = (path_prefix or "").strip()
    if not raw:
        return ""
    segments = [
        safe_namespace_path_segment(segment)
        for segment in raw.split("/")
        if segment.strip()
    ]
    if not segments:
        return ""
    return "/" + "/".join(segments)


def _prefix_price_check(links: Any, prefix: str) -> None:
    if not isinstance(links, dict):
        return
    price_check = links.get("price_check")
    if not isinstance(price_check, dict):
        return
    href = price_check.get("href")
    if isinstance(href, str) and href.startswith(PRICE_CHECK_CANONICAL_PREFIX):
        price_check["href"] = f"{prefix}{href}"


def _walk_nodes(node: Any) -> list[Any]:
    """Local deep-walk. Deliberately not imported from app.plugins.json_utils:
    app.plugins.__init__ imports the EXP plugin, which imports this module, so
    reaching back into app.plugins here would be a circular import."""
    nodes = [node]
    if isinstance(node, dict):
        for value in node.values():
            nodes.extend(_walk_nodes(value))
    elif isinstance(node, list):
        for item in node:
            nodes.extend(_walk_nodes(item))
    return nodes


def _unwrap_adapter_log_body(expectation: dict[str, Any], log_type: str) -> None:
    if log_type not in {"Search", "Packages"}:
        return
    http_response = expectation.get("httpResponse")
    if not isinstance(http_response, dict):
        return
    body = http_response.get("body")
    if isinstance(body, dict) and isinstance(body.get("body"), list):
        http_response["body"] = body["body"]
