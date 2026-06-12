"""Helpers for MockServer expectation shaping."""

from __future__ import annotations

from typing import Any

from app.core.exp_paths import apply_exp_mock_path
from app.core.hbs_paths import apply_hbs_mock_path
from app.core.namespace import apply_namespace


def strip_http_request_matchers(expectation: dict[str, Any]) -> dict[str, Any]:
    """Remove httpRequest body/header matchers — match path + method only."""
    http_request = expectation.get("httpRequest")
    if isinstance(http_request, dict):
        http_request.pop("body", None)
        http_request.pop("headers", None)
    return expectation


def finalize_expectation_for_register(
    expectation: dict[str, Any],
    namespace: str,
    supplier_code: str,
    log_type: str,
) -> dict[str, Any]:
    """Apply namespace id and strip request body/header matchers before MockServer register."""
    apply_namespace(expectation, namespace, supplier_code, log_type)
    if supplier_code == "HBS":
        apply_hbs_mock_path(expectation, log_type)
    elif supplier_code == "EXP":
        apply_exp_mock_path(expectation, namespace, log_type)
    return strip_http_request_matchers(expectation)


# Backward-compatible alias used in earlier tests/imports.
strip_http_request_body = strip_http_request_matchers
