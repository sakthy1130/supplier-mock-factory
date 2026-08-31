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


def test_sold_out_accepts_a_booking_index_but_still_builds_no_booking_flow():
    """The index survives sold_out because it answers WHICH package went away.

    It used to be rejected as contradictory. EXT expresses sold_out by dropping that one
    accommodation from the price check, so without an index it cannot know which. Read it
    as "the package under test"; nothing books either way.
    """
    spec = PackageSpec(count=2, room_basis="RO", prices=[100.0, 150.0],
                       prebooking_status=PreBookingStatus.sold_out,
                       booking_package_index=1)
    assert spec.booking_package_index == 1

    built = _build(PreBookingStatus.sold_out, book_idx=0)
    assert set(built) == {"Search", "Packages", "PreBooking"}, (
        "sold_out drops the booking flow whatever the index says"
    )


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


# ── canPrebook and the prebook URL are INDEPENDENT ────────────────────────────

def _opt_for(**kw):
    """Build a scenario and return the contract opt urls it would produce."""
    from app.core.mock_urls import build_mock_opt_urls, extract_paths_from_built

    request = _request(PreBookingStatus.available, book_idx=0)
    request.suppliers[0].packages = PackageSpec(
        count=1, room_basis="RO", room_names=["A"], prices=[PACKAGE_PRICE],
        booking_package_index=0, **kw,
    )
    with use_env("stg"):
        built = ScenarioEngine().build_expectations(request)
    spec = request.suppliers[0].packages
    opt = build_mock_opt_urls(
        "http://mock", extract_paths_from_built(built).get("EXP", {}),
        supplier_code="EXP", include_prebook_url=spec.prebook_url is not False,
    )
    return request.suppliers[0], opt, {b.log_type for b in built}


def _perm(supplier):
    from app.core.contract_provisioner import _scenario_permissions

    return _scenario_permissions(supplier)


def test_case_1_permission_off_url_kept():
    supplier, opt, _ = _opt_for(can_prebook=False)
    assert _perm(supplier) == {"canPrebook": False}
    assert "overridePrebookUrl" in opt


def test_case_2_permission_on_url_omitted():
    supplier, opt, _ = _opt_for(can_prebook=True, prebook_url=False)
    assert _perm(supplier) == {"canPrebook": True}
    assert "overridePrebookUrl" not in opt


def test_case_3_permission_off_and_url_omitted():
    supplier, opt, _ = _opt_for(can_prebook=False, prebook_url=False)
    assert _perm(supplier) == {"canPrebook": False}
    assert "overridePrebookUrl" not in opt


def test_neither_set_is_unchanged():
    supplier, opt, types = _opt_for()
    assert _perm(supplier) == {}
    assert "overridePrebookUrl" in opt
    assert "PreBooking" in types


def test_omitting_the_url_keeps_a_mock_url_on_the_standard_field():
    """core's E2002 "Booking url is blocked" reads prebookingUrl, not the override.
    Leaving it pointed at api.ean.com would block the whole flow, so the fallback
    must still fill it with a mock host."""
    _, opt, _ = _opt_for(prebook_url=False)
    assert "overridePrebookUrl" not in opt
    assert opt["prebookingUrl"].startswith("http://mock")


def test_the_mock_is_still_built_either_way():
    """Both flags are contract-level. Dropping the mock too would make the axes
    non-independent, which is the thing this design exists to avoid."""
    for kw in ({"can_prebook": False}, {"prebook_url": False},
               {"can_prebook": False, "prebook_url": False}):
        _, _, types = _opt_for(**kw)
        assert "PreBooking" in types, kw


def test_a_status_that_cannot_be_reached_is_rejected():
    with pytest.raises(ValueError, match="never price-checks"):
        PackageSpec(count=1, room_basis="RO", prices=[100.0],
                    can_prebook=False, prebooking_status=PreBookingStatus.sold_out)
    with pytest.raises(ValueError, match="not reachable"):
        PackageSpec(count=1, room_basis="RO", prices=[100.0],
                    prebook_url=False, prebooking_status=PreBookingStatus.sold_out)


# ── Scenario 4: "prebooking not enabled" has TWO halves ────────────────────────

def test_supplier_prebooking_is_restored_on_teardown():
    """The supplier record is shared, so a scenario that changes it MUST put it back.

    Without the restore breadcrumb a torn-down scenario would leave prebooking off for
    every other scenario in the env. None means the key was absent and must be restored
    as absence, not as false.
    """
    import inspect

    from app.core import orchestrator

    src = inspect.getsource(orchestrator)
    assert "_apply_supplier_prebooking" in src
    assert "_restore_supplier_prebooking" in src
    # The restore runs FIRST in the body, before any step that could raise and skip
    # it — leaving the shared record altered is worse than a partial teardown.
    body = src[src.index("async def teardown_scenario"):]
    body = body[body.index(") -> ScenarioBundle:"):]
    assert body.index("_restore_supplier_prebooking") < body.index(
        "br_provisioner.cleanup"
    ), "restore must run before the rest of teardown"


def test_restore_puts_an_absent_key_back_as_absent():
    """stg's EXP has no prebooking key at all. Restoring it as false would silently
    change the supplier from 'not advertised' to 'explicitly disabled'."""
    import inspect

    from app.integrations.backoffice import BackofficeClient

    src = inspect.getsource(BackofficeClient.restore_supplier_prebooking)
    assert 'endpoints.pop("prebooking", None)' in src


def test_missing_prebooking_key_is_not_the_same_as_false():
    from app.api.routes.suppliers import _as_bool

    assert _as_bool(None) is None          # key absent -> not advertised
    assert _as_bool("true") is True
    assert _as_bool("false") is False
    assert _as_bool(True) is True


def test_the_three_prebooking_levers_are_independent():
    """contract permission, contract URL, supplier endpoint — none implies another."""
    spec = PackageSpec(
        count=1, room_basis="RO", prices=[100.0],
        can_prebook=True, prebook_url=False, supplier_prebooking=False,
    )
    assert (spec.can_prebook, spec.prebook_url, spec.supplier_prebooking) == (True, False, False)
