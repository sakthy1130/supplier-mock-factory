"""Namespace isolation for shared MockServer via expectation id."""

from __future__ import annotations

NAMESPACE_HEADER = "X-Mock-Scenario-Id"

ALL_SCENARIO_LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

SCENARIO_SUPPLIER_CODES = ("HBS", "EXP", "RHK")


def build_expectation_id(namespace: str, supplier_code: str, log_type: str) -> str:
    safe = namespace.lower().replace(" ", "-")
    return f"smf-{safe}-{supplier_code}-{log_type}".lower()


def expectation_ids_for_namespace(
    namespace: str,
    suppliers: list[str] | None = None,
) -> list[str]:
    codes = tuple(suppliers) if suppliers else SCENARIO_SUPPLIER_CODES
    return [
        build_expectation_id(namespace, supplier_code, log_type)
        for supplier_code in codes
        for log_type in ALL_SCENARIO_LOG_TYPES
    ]


def apply_namespace(
    expectation: dict,
    namespace: str,
    supplier_code: str,
    log_type: str,
) -> dict:
    """Tag expectation with stable id for teardown; no httpRequest header matcher."""
    expectation["id"] = build_expectation_id(namespace, supplier_code, log_type)
    return expectation
