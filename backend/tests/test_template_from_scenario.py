"""Saving a provisioned scenario as a template, and running it back.

The two shapes are inverses: a scenario stores packages as parallel ARRAYS, a template
as a list of ROWS. These tests pin that the inversion is lossless for everything that
makes the scenario reproducible.
"""

from __future__ import annotations

import pytest

from app.models.run_template import RunTemplateRequest
from app.models.scenario_template import (
    TEMPLATE_KIND_PREBOOKING,
    ScenarioTemplate,
    SupplierTemplatePackages,
    TemplatePackageRow,
)
from app.api.routes.run_template import build_scenario_request_from_template


def _template(**supplier_overrides) -> ScenarioTemplate:
    from datetime import datetime, timezone

    supplier = {
        "supplier": "EXP",
        "supplier_currency": "USD",
        "contract_currency": "USD",
        "packages": [
            TemplatePackageRow(room_name="A", room_basis="RO", price=100.0),
            TemplatePackageRow(room_name="B", room_basis="RO", price=200.0),
        ],
        **supplier_overrides,
    }
    return ScenarioTemplate(
        id="t1", label="PreBooking SoldOut", description="",
        function=TEMPLATE_KIND_PREBOOKING, atg_hotel_id="1446194",
        suppliers=[SupplierTemplatePackages(**supplier)],
        sb_enabled=False, created_at=datetime.now(timezone.utc),
    )


def _build(template, **request_kwargs):
    return build_scenario_request_from_template(
        template,
        RunTemplateRequest(environment="stg", **request_kwargs),
        namespace="qa-tpl", check_in="2026-09-01", check_out="2026-09-03",
        hotel_id="1446194", template_id="t1",
    )


def test_template_carries_its_prebooking_status_into_the_scenario():
    built = _build(_template(prebooking_status="price_changed", prebooking_changed_price=90.0))
    spec = built.suppliers[0].packages
    assert spec.prebooking_status.value == "price_changed"
    assert spec.prebooking_changed_price == 90.0


def test_request_overrides_the_template():
    """Same precedence as sb_enabled: the run can override what was saved."""
    template = _template(prebooking_status="price_changed", prebooking_changed_price=90.0)
    built = _build(template, prebooking_status="sold_out")
    assert built.suppliers[0].packages.prebooking_status.value == "sold_out"


def test_sold_out_template_drops_the_booking_index():
    """PackageSpec rejects the pair, so a template saved bookable then switched to
    sold_out must not blow up at run time."""
    built = _build(_template(prebooking_status="sold_out"), booking_package_index=0)
    spec = built.suppliers[0].packages
    assert spec.prebooking_status.value == "sold_out"
    assert spec.booking_package_index is None


def test_a_template_with_no_prebooking_fields_is_unchanged():
    """Every template saved before this feature still builds exactly what it did."""
    built = _build(_template(), booking_package_index=1)
    spec = built.suppliers[0].packages
    assert spec.prebooking_status.value == "available"
    assert spec.prebooking_changed_price is None
    assert spec.booking_package_index == 1


def test_scenario_to_template_inverts_the_package_shape(monkeypatch):
    """prices[i]/room_names[i]/… -> rows[i], with the per-supplier settings carried."""
    from app.services import scenario_template_service as svc

    saved = {}

    class _Record:
        status = "READY"
        request_json = {
            "atg_hotel_id": "1446194",
            "sb_enabled": False,
            "suppliers": [{
                "code": "EXP",
                "contract_currency": "USD",
                "assignment_target": "apikey",
                "packages": {
                    "count": 3,
                    "prices": [100.0, 200.0, 300.0],
                    "room_names": ["A", "B", "C"],
                    "room_basis": ["RO", "BB", "RO"],
                    "refundable": [True, False, True],
                    "supplier_currency": "USD",
                    "prebooking_status": "sold_out",
                    "prebooking_changed_price": None,
                },
            }],
        }

    class _Store:
        scenarios = type("S", (), {"get": staticmethod(lambda _id: _Record())})()

    monkeypatch.setattr(svc, "create_template", lambda db, payload: saved.setdefault("p", payload))
    svc.template_from_scenario(_Store(), "sid", label="PreBooking SoldOut",
                               function=TEMPLATE_KIND_PREBOOKING)

    payload = saved["p"]
    assert payload.label == "PreBooking SoldOut"
    assert payload.function == TEMPLATE_KIND_PREBOOKING
    supplier = payload.suppliers[0]
    assert [r.room_name for r in supplier.packages] == ["A", "B", "C"]
    assert [r.price for r in supplier.packages] == [100.0, 200.0, 300.0]
    assert [r.room_basis for r in supplier.packages] == ["RO", "BB", "RO"]
    assert [r.refundable for r in supplier.packages] == [True, False, True]
    assert supplier.prebooking_status.value == "sold_out"


def test_a_scenario_that_is_not_ready_is_refused():
    from fastapi import HTTPException
    from app.services import scenario_template_service as svc

    class _Store:
        scenarios = type("S", (), {
            "get": staticmethod(lambda _id: type("R", (), {"status": "FAILED", "request_json": {}})())
        })()

    with pytest.raises(HTTPException) as exc:
        svc.template_from_scenario(_Store(), "sid", label="x")
    assert exc.value.status_code == 409


def test_persisted_suppliers_keep_every_field(monkeypatch):
    """_apply_payload used to list suppliers_json fields by hand, which silently
    dropped prebooking_status when it was added. Pin that the round-trip is lossless."""
    from app.db.models import ScenarioTemplateRecord
    from app.models.scenario_template import ScenarioTemplateCreate
    from app.services import scenario_template_service as svc

    payload = ScenarioTemplateCreate(
        label="PreBooking SoldOut",
        atg_hotel_id="1446194",
        suppliers=[
            SupplierTemplatePackages(
                supplier="EXP",
                packages=[TemplatePackageRow(room_name="A", price=100.0)],
                prebooking_status="price_changed",
                prebooking_changed_price=90.0,
            )
        ],
    )
    record = ScenarioTemplateRecord(id="t1")
    svc._apply_payload(record, payload)

    stored = record.suppliers_json[0]
    assert stored["prebooking_status"] == "price_changed"
    assert stored["prebooking_changed_price"] == 90.0
    # and it survives being read back into the model
    monkeypatch.setattr(svc, "has_template_child_condition", lambda *_a, **_k: False)
    rebuilt = svc._record_to_model(record)
    supplier = rebuilt.suppliers[0]
    assert supplier.prebooking_status.value == "price_changed"
    assert supplier.prebooking_changed_price == 90.0


def test_booking_index_and_occupancy_survive_the_round_trip(monkeypatch):
    """The gap that made a saved template behave differently from its scenario.

    A scenario booking package 0 became a template with no booking index, so running
    it gave search+packages only — no Booking/GetOrder mocks. Same for a non-default
    occupancy, where an adapter drops rates whose occupancy != the request.
    """
    from app.services import scenario_template_service as svc

    saved = {}

    class _Record:
        status = "READY"
        request_json = {
            "atg_hotel_id": "1446194",
            "suppliers": [{
                "code": "EXP", "contract_currency": "USD",
                "packages": {
                    "count": 3, "prices": [100.0, 200.0, 300.0],
                    "room_names": ["A", "B", "C"], "room_basis": ["RO", "RO", "RO"],
                    "refundable": [True, True, True], "supplier_currency": "USD",
                    "booking_package_index": 2,
                    "adults": 3, "child_ages": [7], "room_count": 2,
                },
            }],
        }

    class _Store:
        scenarios = type("S", (), {"get": staticmethod(lambda _id: _Record())})()

    monkeypatch.setattr(svc, "create_template", lambda db, payload: saved.setdefault("p", payload))
    svc.template_from_scenario(_Store(), "sid", label="Bookable")

    supplier = saved["p"].suppliers[0]
    assert supplier.booking_package_index == 2
    assert supplier.adults == 3
    assert supplier.child_ages == [7]
    assert supplier.room_count == 2

    # ...and running that template reproduces them, with no index in the request
    built = build_scenario_request_from_template(
        _template_with(supplier),
        RunTemplateRequest(environment="stg"),
        namespace="qa-rt", check_in="2026-09-01", check_out="2026-09-03",
        hotel_id="1446194", template_id="t1",
    )
    spec = built.suppliers[0].packages
    assert spec.booking_package_index == 2, "template's booking index was ignored at run time"
    assert spec.adults == 3 and spec.child_ages == [7] and spec.room_count == 2


def _template_with(supplier):
    from datetime import datetime, timezone

    return ScenarioTemplate(
        id="t1", label="Bookable", description="", function=None,
        atg_hotel_id="1446194", suppliers=[supplier], sb_enabled=False,
        created_at=datetime.now(timezone.utc),
    )


def test_request_index_still_overrides_the_template():
    template = _template_with(
        SupplierTemplatePackages(
            supplier="EXP",
            packages=[TemplatePackageRow(room_name="A", price=100.0),
                      TemplatePackageRow(room_name="B", price=200.0)],
            booking_package_index=0,
        )
    )
    built = build_scenario_request_from_template(
        template, RunTemplateRequest(environment="stg", booking_package_index=1),
        namespace="qa-rt", check_in="2026-09-01", check_out="2026-09-03",
        hotel_id="1446194", template_id="t1",
    )
    assert built.suppliers[0].packages.booking_package_index == 1
