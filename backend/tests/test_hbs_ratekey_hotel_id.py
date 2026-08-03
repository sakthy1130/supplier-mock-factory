"""The HBS rateKey embeds the hotel code (…|W|<dest>|<hotelCode>|<roomCode>|…).
The template bakes the default hotel, so it must be rewritten to the scenario's
resolved supplier hotel id — otherwise the search hotel `code` and the rateKey
disagree and checkrate/booking reference the wrong hotel."""

from __future__ import annotations

import pytest

from app.core.scenario_engine import ScenarioEngine, TEMPLATES_DIR
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierCode, SupplierScenario
from app.plugins.hbs import _rewrite_rate_key_hotel_id

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Search" / "v1.json").exists(),
    reason="HBS templates not available",
)


def test_rewrite_rate_key_hotel_id_replaces_5th_field():
    rk = "20260809|20260811|W|148|156652|DBL.ST|FIT NRF RO|RO||1~1~0"
    out = _rewrite_rate_key_hotel_id(rk, "1231237")
    assert out.split("|")[4] == "1231237"
    # other fields untouched
    assert out.split("|")[3] == "148"
    assert out.split("|")[5] == "DBL.ST"


def test_rewrite_rate_key_hotel_id_leaves_nonstandard_untouched():
    assert _rewrite_rate_key_hotel_id("no-pipes-here", "1231237") == "no-pipes-here"


def test_hbs_search_and_packages_ratekey_matches_resolved_hotel():
    req = ScenarioRequest(
        namespace="qa-hbs-rk",
        check_in="2026-08-09",
        check_out="2026-08-11",
        atg_hotel_id="9999999",
        supplier_hotel_ids={"HBS": "1231237"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.HBS,
                packages=PackageSpec(count=1, room_basis="RO", room_names=["A"], prices=[100.0], refundable=[False]),
            )
        ],
    )
    built = {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(req) if b.supplier_code == "HBS"}
    for log_type in ("Search", "Packages"):
        hotel = built[log_type]["httpResponse"]["body"]["hotels"]["hotels"][0]
        assert hotel["code"] == 1231237
        rate_key = hotel["rooms"][0]["rates"][0]["rateKey"]
        assert rate_key.split("|")[4] == "1231237", f"{log_type} rateKey hotel id not rewritten: {rate_key}"
