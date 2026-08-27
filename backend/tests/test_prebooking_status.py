"""PreBooking status variants for EXP: available / price_changed / sold_out.

partial_sold_out is deliberately out of scope — on EXP that is a different API
(POST /v3/properties/{id}/rooms, per-room status) which the core only calls for a
2+ room search, and SMF has no multi-room concept yet.
"""

from __future__ import annotations

import pytest

from app.core.scenario_engine import ScenarioEngine, TEMPLATES_DIR
from app.env_context import use_env
from app.models.scenario import (
    PackageSpec,
    PreBookingStatus,
    ScenarioRequest,
    SupplierCode,
    SupplierScenario,
)

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "EXP" / "PreBooking" / "v1.json").exists(),
    reason="EXP templates not available",
)

PACKAGE_PRICE = 100.0
CHANGED_PRICE = 140.0


def _request(status, changed=None, book_idx=0):
    return ScenarioRequest(
        namespace="qa-prebooking",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"EXP": "10469244"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode("EXP"),
                packages=PackageSpec(
                    count=1, room_basis="RO", room_names=["A"], prices=[PACKAGE_PRICE],
                    booking_package_index=book_idx,
                    prebooking_status=status,
                    prebooking_changed_price=changed,
                ),
            )
        ],
    )


def _build(status, changed=None, book_idx=0):
    with use_env("stg"):
        built = ScenarioEngine().build_expectations(_request(status, changed, book_idx))
    return {b.log_type: b.expectation for b in built}


def _inclusive(totals):
    value = totals.get("inclusive")
    if isinstance(value, dict):
        return float(value.get("request_currency", {}).get("value"))
    return float(value)


# ── which body each status serves ──────────────────────────────────────────────

def test_available_serves_the_v1_body_and_the_full_chain():
    built = _build(PreBookingStatus.available)
    assert built["PreBooking"]["httpResponse"]["body"]["status"] == "available"
    # the booking flow is intact
    assert {"Booking", "GetOrder", "CancelOrder"} <= set(built)


def test_price_changed_serves_the_price_changed_body():
    built = _build(PreBookingStatus.price_changed, CHANGED_PRICE)
    body = built["PreBooking"]["httpResponse"]["body"]
    assert body["status"] == "price_changed"
    # the core still needs somewhere to go next
    assert "book" in body["links"]
    assert {"Booking", "GetOrder", "CancelOrder"} <= set(built)


def test_sold_out_serves_a_body_with_no_pricing_and_no_book_link():
    built = _build(PreBookingStatus.sold_out, book_idx=None)
    body = built["PreBooking"]["httpResponse"]["body"]
    assert body["status"] == "sold_out"
    assert not body.get("occupancy_pricing")
    assert "book" not in (body.get("links") or {})


def test_sold_out_stops_the_chain_at_prebooking():
    """No book link means the core cannot proceed, so those mocks would be dead."""
    built = _build(PreBookingStatus.sold_out, book_idx=None)
    assert set(built) == {"Search", "Packages", "PreBooking"}


# ── the changed price actually reaches the right mocks ─────────────────────────

def test_changed_price_lands_in_prebooking_and_getorder_but_not_packages():
    """Search/Packages advertise the package price; the re-quote is what you book at."""
    built = _build(PreBookingStatus.price_changed, CHANGED_PRICE)

    prebooking = built["PreBooking"]["httpResponse"]["body"]["occupancy_pricing"]
    for occ in prebooking.values():
        assert _inclusive(occ["totals"]) == pytest.approx(CHANGED_PRICE, abs=0.01)

    pricing = built["GetOrder"]["httpResponse"]["body"]["rooms"][0]["rate"]["pricing"]
    order_total = pricing["totals"]["inclusive"]["billable_currency"]["value"]
    assert float(order_total) == pytest.approx(CHANGED_PRICE, abs=0.01)

    # Packages keeps the original — if this ever matches, the test has lost its point.
    packages_body = built["Packages"]["httpResponse"]["body"]
    properties = packages_body if isinstance(packages_body, list) else packages_body["body"]
    rate = properties[0]["rooms"][0]["rates"][0]
    for occ in rate["occupancy_pricing"].values():
        assert _inclusive(occ["totals"]) == pytest.approx(PACKAGE_PRICE, abs=0.01)


def test_available_getorder_still_uses_the_package_price():
    built = _build(PreBookingStatus.available)
    pricing = built["GetOrder"]["httpResponse"]["body"]["rooms"][0]["rate"]["pricing"]
    order_total = pricing["totals"]["inclusive"]["billable_currency"]["value"]
    assert float(order_total) == pytest.approx(PACKAGE_PRICE, abs=0.01)


# ── the default path is untouched ──────────────────────────────────────────────

def test_unset_status_builds_byte_identical_mocks():
    """This is what protects every existing scenario and saved template."""
    import json

    with use_env("stg"):
        engine = ScenarioEngine()
        explicit = engine.build_expectations(_request(PreBookingStatus.available))
        default_spec = _request(PreBookingStatus.available)
        # rebuild with the field never mentioned
        default_spec.suppliers[0].packages = PackageSpec(
            count=1, room_basis="RO", room_names=["A"], prices=[PACKAGE_PRICE],
            booking_package_index=0,
        )
        implicit = engine.build_expectations(default_spec)

    assert json.dumps([b.expectation for b in explicit], sort_keys=True) == json.dumps(
        [b.expectation for b in implicit], sort_keys=True
    )


# ── rejected combinations ──────────────────────────────────────────────────────

def test_price_changed_without_a_price_is_rejected():
    with pytest.raises(ValueError, match="needs prebooking_changed_price"):
        PackageSpec(count=1, room_basis="RO", prices=[100.0],
                    prebooking_status=PreBookingStatus.price_changed)


def test_changed_price_on_another_status_is_rejected():
    with pytest.raises(ValueError, match="only applies to prebooking_status"):
        PackageSpec(count=1, room_basis="RO", prices=[100.0],
                    prebooking_status=PreBookingStatus.sold_out,
                    prebooking_changed_price=140.0)


def test_sold_out_with_a_booking_index_is_rejected():
    """Asking to book a sold-out scenario is contradictory — say so, don't guess."""
    with pytest.raises(ValueError, match="drop booking_package_index"):
        PackageSpec(count=1, room_basis="RO", prices=[100.0],
                    prebooking_status=PreBookingStatus.sold_out,
                    booking_package_index=0)


def test_a_missing_variant_file_fails_loudly(tmp_path):
    """Never silently fall back to v1.json — the scenario would report a status it
    did not actually provision."""
    (tmp_path / "EXP" / "PreBooking").mkdir(parents=True)
    (tmp_path / "EXP" / "PreBooking" / "v1.json").write_text("{}")
    engine = ScenarioEngine(templates_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="sold_out.json"):
        engine._load_supplier_templates("EXP", ["PreBooking"], PreBookingStatus.sold_out)


# ── run mode: the same READY scenario, driven two different distances ──────────

def test_run_mode_values():
    """'packages' stops after packages even when a package was picked for booking."""
    from app.api.routes.scenarios import RunMode

    assert [m.value for m in RunMode] == ["packages", "e2e"]
    # e2e is the default, so existing callers that post no mode keep today's behaviour
    import inspect
    from app.api.routes import scenarios as scenarios_module

    default = inspect.signature(scenarios_module.run_scenario).parameters["mode"].default
    assert default.default is RunMode.e2e


# ── can_prebook: contract permission off, no prebook URL, no mock ──────────────

def test_can_prebook_false_drops_the_prebooking_mock():
    built = _build(PreBookingStatus.available, book_idx=0)
    assert "PreBooking" in built, "baseline should have one"

    with use_env("stg"):
        request = _request(PreBookingStatus.available, book_idx=0)
        request.suppliers[0].packages = PackageSpec(
            count=1, room_basis="RO", room_names=["A"], prices=[PACKAGE_PRICE],
            booking_package_index=0, can_prebook=False,
        )
        off = {b.log_type for b in ScenarioEngine().build_expectations(request)}
    assert "PreBooking" not in off
    # the rest of the chain is untouched — this is about the price check only
    assert {"Search", "Packages", "Booking", "GetOrder", "CancelOrder"} <= off


def test_can_prebook_false_omits_the_override_prebook_url():
    """The URL is derived from the PreBooking mock path, so dropping the mock must
    leave overridePrebookUrl absent rather than pointing somewhere wrong."""
    from app.core.mock_urls import build_mock_opt_urls, extract_paths_from_built

    with use_env("stg"):
        request = _request(PreBookingStatus.available, book_idx=0)
        request.suppliers[0].packages = PackageSpec(
            count=1, room_basis="RO", room_names=["A"], prices=[PACKAGE_PRICE],
            booking_package_index=0, can_prebook=False,
        )
        built = ScenarioEngine().build_expectations(request)
    paths = extract_paths_from_built(built)
    opt = build_mock_opt_urls("http://mock", paths.get("EXP", {}), supplier_code="EXP")
    assert "overridePrebookUrl" not in opt


def test_can_prebook_unset_changes_nothing():
    """Absent means absent: the reference contract keeps its own permission."""
    from app.core.contract_provisioner import _scenario_permissions
    from app.models.scenario import SupplierCode, SupplierScenario

    def perms(value):
        return _scenario_permissions(
            SupplierScenario(
                code=SupplierCode("EXP"),
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0], can_prebook=value),
            )
        )

    assert perms(None) == {}
    assert perms(False) == {"canPrebook": False}
    assert perms(True) == {"canPrebook": True}


def test_can_prebook_false_with_a_prebooking_status_is_rejected():
    """A status you can never observe is a mistake worth naming, not honouring."""
    with pytest.raises(ValueError, match="never price-checks"):
        PackageSpec(count=1, room_basis="RO", prices=[100.0],
                    can_prebook=False, prebooking_status=PreBookingStatus.sold_out)
