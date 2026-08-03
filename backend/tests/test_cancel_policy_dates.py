"""Cancellation-policy dates derive from the scenario's check-in/check-out for
HBS/EXP/EXT: refundable = free until 2 days before check-in, non-refundable =
penalty from the start. Refundability itself still follows the per-package flag."""

from __future__ import annotations

import pytest

from app.core.cancel_policy import free_cancel_deadline
from app.core.scenario_engine import ScenarioEngine, TEMPLATES_DIR
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierCode, SupplierScenario

CHECK_IN = "2026-09-10"
CHECK_OUT = "2026-09-14"
DEADLINE = "2026-09-08"  # check-in - 2 days
# Shared instant every supplier must emit so a rebooker sees identical dateFrom.
DEADLINE_TS = "2026-09-08T00:00:00.000+05:30"

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Search" / "v1.json").exists(),
    reason="Supplier templates not available",
)


def _built(code: str, refundable: bool) -> dict:
    req = ScenarioRequest(
        namespace="qa-cp",
        check_in=CHECK_IN,
        check_out=CHECK_OUT,
        atg_hotel_id="1500003",
        supplier_hotel_ids={code: "156652"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode(code),
                packages=PackageSpec(count=1, room_basis="RO", room_names=["A"], prices=[100.0], refundable=[refundable]),
            )
        ],
    )
    return {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(req) if b.supplier_code == code}


def test_free_cancel_deadline_is_two_days_before_checkin():
    assert free_cancel_deadline(CHECK_IN).isoformat() == DEADLINE


def test_hbs_cancellation_from_derives_from_stay():
    ref = _built("HBS", True)["Search"]["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0]
    cp = ref["cancellationPolicies"][0]
    assert cp["from"] == DEADLINE_TS and cp["amount"] == "0"
    nrf = _built("HBS", False)["Search"]["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0]
    assert nrf["cancellationPolicies"][0]["from"].startswith("2000-01-01")


def test_ext_stay_periods_derive_from_stay():
    dist = _built("EXT", True)["Search"]["httpResponse"]["body"]["body"][0]["accommodations"][0]["distributions"][0]
    cond = dist["conditions"][0]
    assert cond["stayPeriods"][0] == {"from": CHECK_IN, "to": CHECK_OUT}
    # A single penalty tier at the shared 2-day deadline so the adapter-derived
    # dateFrom matches HBS/EXP (the rebooker skips packages whose CP dates differ).
    assert len(cond["penalties"]) == 1
    assert cond["penalties"][0]["daysBeforeArrival"] == 2
    nrf = _built("EXT", False)["Search"]["httpResponse"]["body"]["body"][0]["accommodations"][0]["distributions"][0]
    assert "conditions" not in nrf


def _exp_rate(built: dict) -> dict:
    body = built["Packages"]["httpResponse"]["body"]
    props = body["body"] if isinstance(body, dict) else body
    return props[0]["rooms"][0]["rates"][0]


def test_exp_cancel_penalty_window_derives_from_stay():
    ref = _exp_rate(_built("EXP", True))
    assert ref["refundable"] is True
    assert ref["cancel_penalties"][0]["start"] == DEADLINE_TS
    assert ref["cancel_penalties"][0]["end"] == f"{CHECK_OUT}T00:00:00.000+05:30"
    nrf = _exp_rate(_built("EXP", False))
    assert nrf["refundable"] is False
    assert nrf["cancel_penalties"][0]["start"].startswith("2000-01-01")
