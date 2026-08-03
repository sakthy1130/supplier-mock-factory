"""Every supplier's Search/Packages mock must report the same adult occupancy
(SEARCH_ADULTS), or an adapter drops packages whose occupancy != the request —
which is what made EXT (a 2-adult mock) vanish from a 1-adult search while HBS
(a 1-adult mock) survived."""

from __future__ import annotations

import json
import re

import pytest

from app.core.scenario_engine import SEARCH_ADULTS, ScenarioEngine, TEMPLATES_DIR, _force_adult_occupancy
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierCode, SupplierScenario

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Search" / "v1.json").exists(),
    reason="Supplier templates not available",
)


def _adult_values(body: dict) -> set[str]:
    text = json.dumps(body)
    keys = "adults|adultCount|adultsCount|numberAdults|numberOfAdults|requestedNumberAdults"
    return set(re.findall(rf'"(?:{keys})"\s*:\s*"?(\d+)', text))


@pytest.mark.parametrize("code", ["HBS", "RHK", "CHC", "EXT"])
def test_search_packages_occupancy_normalized(code):
    req = ScenarioRequest(
        namespace="qa-occ",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="156652",
        supplier_hotel_ids={code: "156652"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode(code),
                packages=PackageSpec(count=1, room_basis="RO", room_names=["A"], prices=[100.0]),
            )
        ],
    )
    built = {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(req)}
    for log_type in ("Search", "Packages"):
        body = built[log_type]["httpResponse"].get("body", {})
        values = _adult_values(body)
        assert values in (set(), {str(SEARCH_ADULTS)}), f"{code} {log_type} has mixed occupancy {values}"


def test_force_adult_occupancy_preserves_type_and_skips_children():
    node = {
        "adults": 1,
        "adultCount": "1",
        "children": 0,
        "flag": True,  # bool must not be treated as an adult count
        "rooms": [{"requestedNumberAdults": 1, "numberOfAdults": 1}],
    }
    _force_adult_occupancy(node, 2)
    assert node["adults"] == 2
    assert node["adultCount"] == "2"  # string type preserved
    assert node["children"] == 0
    assert node["flag"] is True
    assert node["rooms"][0]["requestedNumberAdults"] == 2
    assert node["rooms"][0]["numberOfAdults"] == 2
