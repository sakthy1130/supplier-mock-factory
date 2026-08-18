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

SCENARIO_SUPPLIER_CODES = ("HBS", "EXP", "RHK", "CHC")


def safe_namespace_path_segment(namespace: str) -> str:
    """Normalize a namespace for use as a URL path segment (no case-folding)."""
    return namespace.strip().replace(" ", "-")


def build_expectation_id(namespace: str, supplier_code: str, log_type: str) -> str:
    """`supplier_code` is really the supplier INSTANCE key (see
    app.models.scenario.instance_key_for) — "EXP" for the first EXP entry in a
    scenario, "EXP-2" for the second, so two entries of one supplier don't
    overwrite each other's expectations."""
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


def instance_path_segment(supplier_code: str, instance_key: str) -> str:
    """Extra path segment isolating a repeated supplier's mocks.

    Empty for the first instance (instance_key == supplier_code), so existing mock
    paths are unchanged; "exp-2" for the second EXP entry, whose mocks would
    otherwise sit at the same path and be served to both contracts.
    """
    if not instance_key or instance_key == supplier_code:
        return ""
    return instance_key.lower()
