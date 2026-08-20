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

def build_expectation_id(namespace: str, supplier_code: str, log_type: str) -> str:
    safe = namespace.lower().replace(" ", "-")
    return f"smf-{safe}-{supplier_code}-{log_type}".lower()


def scenario_supplier_codes() -> tuple[str, ...]:
    """Teardown fallback when a scenario row has no stored supplier list.

    Reads the configured suppliers rather than a hardcoded tuple, so a supplier added
    from the Suppliers screen still has its expectations cleaned up. Imported lazily
    because supplier_service reaches back into the database layer.
    """
    from app.services.supplier_service import configured_codes

    return tuple(configured_codes())


def expectation_ids_for_namespace(
    namespace: str,
    suppliers: list[str] | None = None,
) -> list[str]:
    codes = tuple(suppliers) if suppliers else scenario_supplier_codes()
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
