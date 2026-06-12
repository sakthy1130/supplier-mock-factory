"""Build MockServer expectations from Enigma adapter log rows. Port AdapterSidLogToMockExpectationUtil."""

from __future__ import annotations

import copy
import json
import re
import secrets
import string
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PATH_LIKE = re.compile(r"^/[\w\-./~:%+?&=,*#\[\]@!$'()]*$")

ALLOWED_LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

# Ingest skips warning when these are absent.
OPTIONAL_TEMPLATE_LOG_TYPES = frozenset({"CancellationPolicy"})

LOG_TYPE_ALIASES = {
    "prebooking": "PreBooking",
    "cancelorder": "CancelOrder",
    "cancellationpolicy": "CancellationPolicy",
    "getorderresponse": "GetOrder",
    "cancelbooking": "CancelOrder",
}


def canonical_log_type(log_type: str) -> str | None:
    if not log_type or not log_type.strip():
        return None
    trimmed = log_type.strip()
    for allowed in ALLOWED_LOG_TYPES:
        if trimmed.lower() == allowed.lower():
            return allowed
    alias = LOG_TYPE_ALIASES.get(trimmed.lower())
    if alias:
        return alias
    return None


def is_target_log_type(log_type: str) -> bool:
    return canonical_log_type(log_type) is not None


def row_timestamp(row: dict) -> str:
    return str(row.get("timestamp") or "")


def is_get_order_response_row(log_type: str) -> bool:
    return log_type.strip().lower() == "getorderresponse"


def is_outbound_get_order_row(log_type: str) -> bool:
    return canonical_log_type(log_type) == "GetOrder" and not is_get_order_response_row(log_type)


@dataclass
class HttpMatch:
    path: str | None
    method: str | None


@dataclass
class PendingExpectation:
    expectation: dict[str, Any]
    log_type: str


def log_file_stem(log_url: str) -> str:
    if not log_url:
        return "nolog"
    name = log_url.rsplit("/", 1)[-1]
    for suffix in (".json.gz", ".gz", ".json"):
        name = name.replace(suffix, "")
    return name


def resolve_http_status_code(list_row: dict, full_log: dict) -> int:
    meta = list_row.get("meta") or {}
    for source in (meta, full_log):
        code = source.get("httpStatusCode")
        if isinstance(code, int) and code > 0:
            return code
    return 200


def extract_response_body_payload(full_log: dict) -> dict:
    if not full_log:
        return {}
    response = full_log.get("response")
    if isinstance(response, dict):
        body = response.get("body")
        if isinstance(body, dict) and body:
            return copy.deepcopy(body)
        return copy.deepcopy(response)
    return copy.deepcopy(full_log)


def parse_log_json_body(raw: Any) -> Any | None:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return copy.deepcopy(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text[0] == "[":
            return json.loads(text)
        return json.loads(text)
    return None


def extract_request_payload_for_mock(log_detail: dict) -> Any | None:
    if not log_detail:
        return None
    request = log_detail.get("request")
    if isinstance(request, dict):
        if request.get("body") is not None:
            parsed = parse_log_json_body(request.get("body"))
            if parsed is not None:
                return parsed
        if request:
            return copy.deepcopy(request)
    http_req = log_detail.get("httpRequest")
    if isinstance(http_req, dict) and http_req.get("body") is not None:
        parsed = parse_log_json_body(http_req.get("body"))
        if parsed is not None:
            return parsed
    for alt in ("requestBody", "payload"):
        alt_obj = log_detail.get(alt)
        if isinstance(alt_obj, dict) and alt_obj:
            return copy.deepcopy(alt_obj)
    return None


def strip_request_body_header(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    result = copy.deepcopy(payload)
    result.pop("header", None)
    return result


def mock_server_json_body_matcher(payload: Any) -> dict:
    return {
        "type": "JSON",
        "json": strip_request_body_header(payload),
        "matchType": "ONLY_MATCHING_FIELDS",
    }


def build_expectation(
    path: str,
    method: str | None,
    request_body: Any | None,
    response_body: dict,
    status_code: int,
) -> dict:
    # SMF mocks match on path/method only — no request body or header matchers.
    _ = request_body
    http_request: dict[str, Any] = {
        "path": path,
        "method": (method or "POST").strip().upper() or "POST",
    }

    return {
        "httpRequest": http_request,
        "httpResponse": {
            "headers": {"content-type": ["application/json"]},
            "statusCode": status_code,
            "body": response_body,
        },
        "priority": 1000,
    }


def _empty_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nested_opt_string(root: dict | None, child_key: str, leaf_key: str) -> str | None:
    if not root:
        return None
    child = root.get(child_key)
    if not isinstance(child, dict):
        return None
    return _empty_to_none(child.get(leaf_key))


def _meta_string(list_row: dict | None, key: str) -> str | None:
    if not list_row:
        return None
    meta = list_row.get("meta")
    if not isinstance(meta, dict):
        return None
    return _empty_to_none(meta.get(key))


def _first_non_blank(*values: Any) -> str | None:
    for value in values:
        text = _empty_to_none(value)
        if text:
            return text
    return None


def _path_from_url_string(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return _empty_to_none(urlparse(url.strip()).path)
    except Exception:
        return None


def _normalize_path(path: str) -> str:
    text = path.strip()
    if not text.startswith("/"):
        text = f"/{text}"
    return text


def _looks_like_http_path(value: str) -> bool:
    if not value or len(value) < 2 or len(value) > 512:
        return False
    if not value.startswith("/"):
        return False
    return bool(PATH_LIKE.match(value))


def _find_path_like_string(root: dict, max_depth: int) -> str | None:
    frontier: list[Any] = [root]
    depth = 0
    while frontier and depth <= max_depth:
        next_frontier: list[dict] = []
        for node in frontier:
            if not isinstance(node, dict):
                continue
            for value in node.values():
                if isinstance(value, str) and _looks_like_http_path(value):
                    return value.strip()
                if isinstance(value, dict):
                    next_frontier.append(value)
        frontier = next_frontier
        depth += 1
    return None


def resolve_http_path_and_method(list_row: dict, full_log: dict) -> HttpMatch:
    method = _first_non_blank(
        full_log.get("httpMethod"),
        full_log.get("method"),
        _nested_opt_string(full_log, "request", "httpMethod"),
        _nested_opt_string(full_log, "request", "method"),
        list_row.get("httpMethod"),
        _meta_string(list_row, "httpMethod"),
    )

    path = _first_non_blank(
        full_log.get("path"),
        full_log.get("requestPath"),
        full_log.get("resourcePath"),
        full_log.get("requestUri"),
        full_log.get("endpoint"),
        full_log.get("httpPath"),
        _nested_opt_string(full_log, "request", "path"),
        _nested_opt_string(full_log, "request", "requestPath"),
        _nested_opt_string(full_log, "request", "resourcePath"),
        _nested_opt_string(full_log, "request", "requestUri"),
        _nested_opt_string(full_log, "request", "uri"),
        _meta_string(list_row, "path"),
        _meta_string(list_row, "requestPath"),
    )

    if not path:
        path = _path_from_url_string(full_log.get("url"))
    if not path:
        path = _path_from_url_string(_nested_opt_string(full_log, "request", "url"))
    if not path:
        path = _path_from_url_string(_nested_opt_string(full_log, "request", "uri"))
    if not path:
        path = _find_path_like_string(full_log, 4)

    if path:
        path = _normalize_path(path)
    return HttpMatch(path=path, method=method)


def find_reservations_array_in_log_detail(full_log: dict) -> list | None:
    if not full_log:
        return None
    response = full_log.get("response")
    if isinstance(response, dict):
        body = response.get("body")
        if isinstance(body, dict):
            reservations = body.get("reservations")
            if isinstance(reservations, list) and reservations:
                return reservations
        reservations = response.get("reservations")
        if isinstance(reservations, list) and reservations:
            return reservations
    reservations = full_log.get("reservations")
    if isinstance(reservations, list) and reservations:
        return reservations
    return None


def extract_confirmed_get_order_distributor_res_id(full_log: dict) -> str | None:
    reservations = find_reservations_array_in_log_detail(full_log)
    if not reservations:
        return None
    for reservation in reservations:
        if not isinstance(reservation, dict):
            continue
        if str(reservation.get("status", "")).strip().lower() != "confirmed":
            continue
        ids = reservation.get("reservationIds")
        if not isinstance(ids, dict):
            continue
        dist = str(ids.get("distributorResId", "")).strip()
        if dist:
            return dist
    return None


def _collect_string_field_deep(node: Any, field_key: str, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == field_key and isinstance(value, str) and value.strip():
                out.add(value)
            else:
                _collect_string_field_deep(value, field_key, out)
    elif isinstance(node, list):
        for item in node:
            _collect_string_field_deep(item, field_key, out)


def _replace_field_values_deep(node: Any, field_key: str, old_to_new: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == field_key and isinstance(value, str):
                replacement = old_to_new.get(value)
                if replacement is not None:
                    node[key] = replacement
            else:
                _replace_field_values_deep(value, field_key, old_to_new)
    elif isinstance(node, list):
        for item in node:
            _replace_field_values_deep(item, field_key, old_to_new)


def _first_distributor_res_id(expectation: dict) -> str | None:
    found: set[str] = set()
    _collect_string_field_deep(expectation, "distributorResId", found)
    return next(iter(found), None)


def _random_derby_res_id_like(samples: set[str], length: int) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for sample in samples:
        if any("a" <= c <= "z" for c in sample):
            alphabet = string.ascii_letters + string.digits
            break
    return "".join(secrets.choice(alphabet) for _ in range(length))


def apply_aligned_derby_res_ids_for_booking_and_get_order(pending: list[PendingExpectation]) -> None:
    if not pending:
        return

    dist_has_booking: dict[str, bool] = {}
    dist_has_get_order: dict[str, bool] = {}
    for item in pending:
        if item.log_type not in ("Booking", "GetOrder"):
            continue
        dist = _first_distributor_res_id(item.expectation)
        if not dist:
            continue
        if item.log_type == "Booking":
            dist_has_booking[dist] = True
        if item.log_type == "GetOrder":
            dist_has_get_order[dist] = True

    dist_to_derbies: dict[str, set[str]] = {}
    for item in pending:
        if item.log_type not in ("Booking", "GetOrder"):
            continue
        dist = _first_distributor_res_id(item.expectation)
        if not dist:
            continue
        if not dist_has_booking.get(dist) or not dist_has_get_order.get(dist):
            continue
        bucket = dist_to_derbies.setdefault(dist, set())
        _collect_string_field_deep(item.expectation, "derbyResId", bucket)

    old_to_new: dict[str, str] = {}
    for derbies in dist_to_derbies.values():
        if not derbies:
            continue
        length = max(len(d) for d in derbies)
        synthetic = _random_derby_res_id_like(derbies, length)
        for old in derbies:
            old_to_new[old] = synthetic

    if not old_to_new:
        return

    for item in pending:
        if item.log_type in ("Booking", "GetOrder"):
            _replace_field_values_deep(item.expectation, "derbyResId", old_to_new)


def build_diagnostic_json(sid: str, list_row: dict, log_url: str, full_log: dict) -> dict:
    meta_keys = list((list_row.get("meta") or {}).keys())
    detail_keys = list(full_log.keys()) if isinstance(full_log, dict) else []
    return {
        "sid": sid,
        "logType": list_row.get("logType"),
        "source": list_row.get("source"),
        "traceId": list_row.get("traceId", ""),
        "logUrl": log_url,
        "metaKeys": meta_keys,
        "detailTopLevelKeys": detail_keys,
        "note": "Could not resolve HTTP path for MockServer httpRequest.",
    }
