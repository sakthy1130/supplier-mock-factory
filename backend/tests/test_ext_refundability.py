"""EXT signals refundability via the distribution's cancellation `conditions`,
not just `noRefundable`: refundable = noRefundable:false + conditions[penalties];
non-refundable = noRefundable:true + NO conditions. The template ships without
conditions, so the plugin must build/strip them per the selected flag."""

from __future__ import annotations

import pytest

from app.core.scenario_engine import ScenarioEngine, TEMPLATES_DIR
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierCode, SupplierScenario

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "EXT" / "Search" / "v1.json").exists(),
    reason="EXT templates not available",
)


def _ext_accommodation(refundable: bool) -> dict:
    req = ScenarioRequest(
        namespace="qa-ext-ref",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1500003",
        supplier_hotel_ids={"EXT": "1500003"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXT,
                packages=PackageSpec(count=1, room_basis="RO", room_names=["A"], prices=[100.0], refundable=[refundable]),
            )
        ],
    )
    built = {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(req) if b.supplier_code == "EXT"}
    return built["Search"]["httpResponse"]["body"]["body"][0]["accommodations"][0]


def test_ext_non_refundable_has_no_conditions():
    acc = _ext_accommodation(False)
    assert acc["noRefundable"] is True
    assert "conditions" not in acc["distributions"][0]


def test_ext_refundable_has_conditions_with_penalties():
    acc = _ext_accommodation(True)
    assert acc["noRefundable"] is False
    conditions = acc["distributions"][0]["conditions"]
    assert isinstance(conditions, list) and conditions
    assert conditions[0]["penalties"]
    assert "isMerged" in conditions[0]
