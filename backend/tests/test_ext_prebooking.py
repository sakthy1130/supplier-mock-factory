"""EXT PreBooking: a price check that re-reads the distribution-details contract.

Extranet has no separate price-check API and no status field in its body, so the three
statuses are expressed structurally: `available` answers exactly what Packages answered,
`price_changed` reprices the package under test, and `sold_out` removes it. That makes
"the two bodies agree" the property most of these tests are really guarding.
"""

from __future__ import annotations

import json
from collections import defaultdict

import pytest

from app.core.contract_provisioner import _apply_forced_permission, _apply_scenario_permission
from app.core.scenario_engine import ScenarioEngine, TEMPLATES_DIR
from app.env_context import use_env
from app.models.scenario import (
    PackageSpec,
    PreBookingStatus,
    ScenarioRequest,
    SupplierCode,
    SupplierScenario,
)
from app.services import supplier_service
from app.services.supplier_service import get_supplier_config

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "EXT" / "PreBooking" / "v1.json").exists(),
    reason="EXT templates not available",
)

PRICES = [100.0, 150.0, 200.0]
CHANGED_PRICE = 999.0
CHECK_IN, CHECK_OUT, NIGHTS = "2026-09-01", "2026-09-03", 2


def _build(status=PreBookingStatus.available, changed=None, book_idx=0, count=3):
    request = ScenarioRequest(
        namespace="qa-ext-prebook",
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
        atg_hotel_id="1446194",
        supplier_hotel_ids={"EXT": "100000"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode("EXT"),
                packages=PackageSpec(
                    count=count,
                    room_basis=["RO", "BB", "HB"][:count],
                    room_names=["A", "B", "C"][:count],
                    prices=PRICES[:count],
                    refundable=[True, False, True][:count],
                    booking_package_index=book_idx,
                    prebooking_status=status,
                    prebooking_changed_price=changed,
                ),
            )
        ],
    )
    with use_env("stg"):
        supplier_service.invalidate_cache()
        built = ScenarioEngine().build_expectations(request)
    return {b.log_type: b.expectation for b in built}


def _spec(status=PreBookingStatus.available, changed=None, book_idx=0, count=3):
    return PackageSpec(
        count=count,
        room_basis=["RO", "BB", "HB"][:count],
        room_names=["A", "B", "C"][:count],
        prices=PRICES[:count],
        refundable=[True, False, True][:count],
        booking_package_index=book_idx,
        prebooking_status=status,
        prebooking_changed_price=changed,
    )


def _accommodations(expectation):
    return expectation["httpResponse"]["body"]["body"][0]["accommodations"]


def _totals(expectation):
    return [a["totalPrice"] for a in _accommodations(expectation)]


# ── paths ───────────────────────────────────────────────────────────────────────


def test_every_ext_log_type_registers_on_its_own_path():
    """Regression: Search and GetOrder both used to land on /{namespace}/search.

    EXT declares a canonical_base per log type but did not set path_rewrite, so only the
    suffix survived — and Search and GetOrder share the suffix "search", separated solely
    by /distribution vs /accommodation. Two expectations on one (path, method) means one
    silently shadows the other, which MockServer gives no warning about.
    """
    built = _build()
    by_route = defaultdict(list)
    for log_type, expectation in built.items():
        request = expectation["httpRequest"]
        by_route[(request["method"], request["path"])].append(log_type)

    collisions = {route: types for route, types in by_route.items() if len(types) > 1}
    assert not collisions, f"log types sharing a route: {collisions}"
    assert len(by_route) == 6


def test_prebooking_is_not_on_the_packages_path():
    """The whole point of a separate suffix: one expectation cannot serve two bodies."""
    built = _build()
    assert built["PreBooking"]["httpRequest"]["path"].endswith("/distribution/details-prebook")
    assert built["Packages"]["httpRequest"]["path"].endswith("/distribution/details")


# ── the three statuses ──────────────────────────────────────────────────────────


def test_available_answers_exactly_what_packages_answered():
    """Including accommodation ids.

    _mutate_accommodations mints a fresh uuid4 per call, so building the prebook body a
    second time instead of copying the finished one would describe the same rates under
    different ids — the bug this test exists to catch.
    """
    built = _build(PreBookingStatus.available)
    packages = built["Packages"]["httpResponse"]["body"]
    prebook = built["PreBooking"]["httpResponse"]["body"]
    assert json.dumps(prebook, sort_keys=True) == json.dumps(packages, sort_keys=True)
    assert [a["id"] for a in _accommodations(built["PreBooking"])] == [
        a["id"] for a in _accommodations(built["Packages"])
    ]


def test_price_changed_reprices_only_the_package_under_test():
    built = _build(PreBookingStatus.price_changed, changed=CHANGED_PRICE, book_idx=1)

    assert _totals(built["Packages"]) == PRICES, "Packages keeps the original price"
    assert _totals(built["PreBooking"]) == [PRICES[0], CHANGED_PRICE, PRICES[2]]

    # Extranet carries the same money three ways; a partial rewrite is the classic bug.
    changed = _accommodations(built["PreBooking"])[1]
    distribution = changed["distributions"][0]
    assert distribution["priceDetails"]["totalPrice"] == CHANGED_PRICE
    assert distribution["netPricePerNight"] == {
        "2026-09-01": CHANGED_PRICE / NIGHTS,
        "2026-09-02": CHANGED_PRICE / NIGHTS,
    }
    assert distribution["totalPricePerNight"] == distribution["netPricePerNight"]


def test_sold_out_removes_only_that_package_from_the_price_check():
    built = _build(PreBookingStatus.sold_out, book_idx=1)

    assert _totals(built["Packages"]) == PRICES, "the rate is still on offer at search"
    assert _totals(built["PreBooking"]) == [PRICES[0], PRICES[2]], "only index 1 went away"

    surviving = [a["id"] for a in _accommodations(built["PreBooking"])]
    offered = [a["id"] for a in _accommodations(built["Packages"])]
    assert surviving == [offered[0], offered[2]]


def test_sold_out_builds_no_booking_flow():
    built = _build(PreBookingStatus.sold_out, book_idx=1)
    assert set(built) == {"Search", "Packages", "PreBooking"}


# ── contract ────────────────────────────────────────────────────────────────────


def test_forced_canprebook_matches_the_shape_of_its_siblings():
    """EXT's reference contract has no canPrebook key, so there is no type to copy.

    Backoffice returns these flags as "true"/"false" strings on a clone but as real
    booleans on a minimal body. Writing a bare bool into a block of strings produced a
    mixed block, which the provisioner's own docstring warns can make the whole block
    unreadable — so an absent key takes its shape from its siblings.
    """
    with use_env("stg"):
        supplier_service.invalidate_cache()
        config = get_supplier_config("EXT")

    clone = {
        "permission": {
            "isEnable": "true", "canSearch": "true", "canBook": "true",
            "canCancel": "true", "canCancellationPolicies": "false",
            "canPackages": "true", "canOrder": "true",
        }
    }
    _apply_forced_permission(clone, config)
    assert clone["permission"]["canPrebook"] == "true"

    minimal = {"permission": {"isEnable": True, "canSearch": True}}
    _apply_forced_permission(minimal, config)
    assert minimal["permission"]["canPrebook"] is True

    # An empty block has nothing to infer from; the native bool is the safe answer.
    empty: dict = {}
    _apply_forced_permission(empty, config)
    assert empty["permission"]["canPrebook"] is True


def test_a_scenario_can_still_turn_canprebook_off():
    """forced_permission is the supplier default, not a veto on the scenario."""
    with use_env("stg"):
        supplier_service.invalidate_cache()
        config = get_supplier_config("EXT")

    body = {"permission": {"isEnable": "true", "canSearch": "true"}}
    _apply_forced_permission(body, config)
    _apply_scenario_permission(body, {"canPrebook": False})
    assert body["permission"]["canPrebook"] == "false"


# ── the no-op guarantee ─────────────────────────────────────────────────────────


def test_an_unset_status_builds_the_same_mocks_as_an_explicit_available():
    explicit = _build(PreBookingStatus.available)
    with use_env("stg"):
        supplier_service.invalidate_cache()
        unset = ScenarioEngine().build_expectations(
            ScenarioRequest(
                namespace="qa-ext-prebook",
                check_in=CHECK_IN,
                check_out=CHECK_OUT,
                atg_hotel_id="1446194",
                supplier_hotel_ids={"EXT": "100000"},
                suppliers=[
                    SupplierScenario(
                        code=SupplierCode("EXT"),
                        packages=PackageSpec(
                            count=3,
                            room_basis=["RO", "BB", "HB"],
                            room_names=["A", "B", "C"],
                            prices=PRICES,
                            refundable=[True, False, True],
                            booking_package_index=0,
                        ),
                    )
                ],
            )
        )
    unset_by_type = {b.log_type: b.expectation for b in unset}
    assert set(unset_by_type) == set(explicit)

    # Accommodation ids are uuid4 per build, so compare everything else.
    def _scrub(expectation):
        body = json.loads(json.dumps(expectation))
        hotels = body.get("httpResponse", {}).get("body", {}).get("body")
        if isinstance(hotels, list):
            for hotel in hotels:
                for accommodation in hotel.get("accommodations", []) if isinstance(hotel, dict) else []:
                    accommodation.pop("id", None)
        return json.dumps(body, sort_keys=True)

    for log_type in explicit:
        assert _scrub(unset_by_type[log_type]) == _scrub(explicit[log_type]), log_type


# ── the validator actually fires ────────────────────────────────────────────────


def test_linkage_rejects_a_price_check_that_quotes_a_rate_packages_never_offered():
    """A guard that never fires is not a guard.

    The accommodation id is the only thing tying a quote back to the offered rate, and a
    mismatch is silent at run time — core simply fails to find the package it was
    booking — so it has to be caught at build time.
    """
    from app.core.linkage_validator import LinkageError, LinkageValidator

    built = _build(PreBookingStatus.available)
    _accommodations(built["PreBooking"])[1]["id"] = "not-the-offered-rate"

    with use_env("stg"):
        supplier_service.invalidate_cache()
        with pytest.raises(LinkageError, match="do not match Packages"):
            LinkageValidator().validate(built, "EXT", _spec())


def test_linkage_rejects_a_sold_out_check_that_drops_the_wrong_package():
    from app.core.linkage_validator import LinkageError, LinkageValidator

    built = _build(PreBookingStatus.sold_out, book_idx=1)
    # Drop a second one: only the package under test may disappear.
    del _accommodations(built["PreBooking"])[0]

    with use_env("stg"):
        supplier_service.invalidate_cache()
        with pytest.raises(LinkageError, match="drop exactly the package under test"):
            LinkageValidator().validate(
                built, "EXT", _spec(status=PreBookingStatus.sold_out, book_idx=1)
            )
