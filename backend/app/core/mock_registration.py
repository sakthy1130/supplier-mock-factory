"""Inject booking ids and register built expectations on MockServer."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.booking_id_injector import BOOKING_FLOW_LOG_TYPES, BookingIdInjector
from app.core.scenario_engine import REPO_ROOT, BuiltExpectation
from app.integrations.mock_server import MockServerClient

FIELD_MAPS_DIR = REPO_ROOT / "field-maps"


async def register_built_expectations(
    built: list[BuiltExpectation],
    booking_ids: dict[str, str] | None = None,
    mock_client: MockServerClient | None = None,
) -> dict[str, str]:
    """
    Inject per-supplier booking ids into book/getOrder/cancel, then register all expectations.
    Returns instance_key -> booking_id map (instance_key == supplier_code unless the
    scenario carries the same supplier more than once).
    """
    injector = BookingIdInjector()
    assigned_ids: dict[str, str] = {}
    grouped: dict[str, list[BuiltExpectation]] = {}
    for item in built:
        grouped.setdefault(item.instance_key, []).append(item)

    client = mock_client or MockServerClient()
    if mock_client is not None:
        for instance_key, items in grouped.items():
            assigned_ids[instance_key] = await _inject_and_register_supplier(
                injector,
                client,
                items[0].supplier_code,
                items,
                (booking_ids or {}).get(instance_key),
            )
        return assigned_ids

    async with client:
        for instance_key, items in grouped.items():
            assigned_ids[instance_key] = await _inject_and_register_supplier(
                injector,
                client,
                items[0].supplier_code,
                items,
                (booking_ids or {}).get(instance_key),
            )
    return assigned_ids


async def refresh_booking_flow_expectations(
    built: list[BuiltExpectation],
    mock_client: MockServerClient | None = None,
) -> dict[str, str]:
    """Re-inject new booking ids and re-register Booking/GetOrder/CancelOrder only."""
    injector = BookingIdInjector()
    assigned_ids: dict[str, str] = {}
    grouped: dict[str, list[BuiltExpectation]] = {}
    for item in built:
        if item.log_type not in BOOKING_FLOW_LOG_TYPES:
            continue
        grouped.setdefault(item.instance_key, []).append(item)

    client = mock_client or MockServerClient()

    async def _run() -> None:
        for instance_key, items in grouped.items():
            assigned_ids[instance_key] = await _inject_and_register_supplier(
                injector,
                client,
                items[0].supplier_code,
                items,
                booking_id=None,
            )

    if mock_client is not None:
        await _run()
    else:
        async with client:
            await _run()
    return assigned_ids


async def _inject_and_register_supplier(
    injector: BookingIdInjector,
    client: MockServerClient,
    supplier_code: str,
    items: list[BuiltExpectation],
    booking_id: str | None,
) -> str:
    field_map = _load_field_map(supplier_code)
    by_type = {item.log_type: item.expectation for item in items}
    # No Booking expectation means this supplier's booking flow was intentionally
    # not built (no package selected) — register the search/package mocks as-is
    # and skip booking-id injection, which requires a Booking expectation.
    if "Booking" not in by_type:
        await client.register_expectations([item.expectation for item in items])
        return ""
    new_id = injector.inject(by_type, supplier_code, field_map, booking_id=booking_id)
    await client.register_expectations([item.expectation for item in items])
    return new_id


def _load_field_map(supplier_code: str) -> dict:
    path = FIELD_MAPS_DIR / f"{supplier_code}.json"
    if not path.exists():
        return {"supplier": supplier_code, "paths": {}}
    return json.loads(path.read_text(encoding="utf-8"))
