"""CHC (Choice) supplier plugin + linkage tests."""

import pytest

from app.core.scenario_engine import ScenarioEngine
from app.plugins.json_utils import deep_copy
from app.models.scenario import (
    PackageSpec,
    ScenarioRequest,
    SupplierCode,
    SupplierScenario,
)
from app.plugins import PLUGINS
from app.plugins.chc import ChcMockPlugin


def _chc_request(spec: PackageSpec) -> ScenarioRequest:
    return ScenarioRequest(
        namespace="qa-chc-test",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"CHC": "GB999"},
        suppliers=[SupplierScenario(code=SupplierCode.CHC, packages=spec)],
    )


def test_chc_registered():
    assert "CHC" in PLUGINS
    assert isinstance(PLUGINS["CHC"], ChcMockPlugin)


def test_matches_derby_bts_adapter():
    plugin = ChcMockPlugin()
    assert plugin.matches_adapter_source("hotels-derby-bts-adapter")
    assert not plugin.matches_adapter_source("hotels-rhk-adapter-service-staging")


def test_build_chc_scenario_prices_meal_and_refundability():
    spec = PackageSpec(
        count=3,
        room_basis="BB",
        prices=[111, 222, 333],
        refundable=[True, False, True],
        supplier_currency="SAR",
    )
    built = {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(_chc_request(spec))}

    rates = built["Packages"]["httpResponse"]["body"]["roomRates"]
    assert built["Packages"]["httpResponse"]["body"]["hotelId"] == "GB999"
    assert len(rates) == 3

    for rate, price, refundable in zip(rates, [111.0, 222.0, 333.0], [True, False, True]):
        assert rate["mealPlan"] == "BB"
        assert rate["currency"] == "SAR"
        assert rate["amountBeforeTax"] == [price]
        assert rate["amountAfterTax"] == [price]
        penalties = rate["cancelPolicy"]["cancelPenalties"]
        assert len(penalties) == 1
        assert not penalties[0].get("noShow")
        assert isinstance(penalties[0].get("cancelDeadline"), dict)
        assert rate["cancelPolicy"]["code"] in {"AD0_0", "AD100P_100P"}
        assert penalties[0]["penaltyCharge"]["percent"] == (0 if refundable else 100)

    search_rates = built["Search"]["httpResponse"]["body"]["availHotels"][0]["availRoomRates"]
    assert all(rate["currency"] == "SAR" for rate in search_rates)
    for rate in search_rates:
        penalties = rate["cancelPolicy"]["cancelPenalties"]
        assert len(penalties) == 1
        assert not penalties[0].get("noShow")
        assert isinstance(penalties[0].get("cancelDeadline"), dict)
        assert rate["cancelPolicy"]["code"] in {"AD0_0", "AD100P_100P"}


def test_chc_cancel_policy_strips_no_show_keeps_template_code():
    from app.plugins.chc import _apply_cancel_policy

    rate = {
        "cancelPolicy": {
            "code": "4PM1D100P_100P",
            "cancelPenalties": [
                {
                    "noShow": False,
                    "cancelDeadline": {"deadline": "4PM"},
                    "penaltyCharge": {"percent": 100},
                },
                {"noShow": True, "penaltyCharge": {"percent": 100}},
            ],
        }
    }
    _apply_cancel_policy(rate, is_refundable=True, log_type="Packages")
    assert rate["cancelPolicy"]["code"] == "AD0_0"
    assert len(rate["cancelPolicy"]["cancelPenalties"]) == 1
    assert rate["cancelPolicy"]["cancelPenalties"][0]["penaltyCharge"]["percent"] == 0
    assert isinstance(rate["cancelPolicy"]["cancelPenalties"][0].get("cancelDeadline"), dict)

    rate_nrf = deep_copy(rate)
    _apply_cancel_policy(rate_nrf, is_refundable=False, log_type="Packages")
    assert rate_nrf["cancelPolicy"]["code"] == "AD100P_100P"
    assert rate_nrf["cancelPolicy"]["cancelPenalties"][0]["penaltyCharge"]["percent"] == 100


def test_chc_linkage_aligns_packages_and_prebook_to_search():
    """Packages/PreBooking must match Search occupancy + rate identity, else the BTS
    adapter reconciles them away and returns zero packages."""
    spec = PackageSpec(count=2, room_basis="RO", prices=[100, 200], refundable=[True, False])
    built = {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(_chc_request(spec))}

    search_rate = built["Search"]["httpResponse"]["body"]["availHotels"][0]["availRoomRates"][0]
    s_room, s_rate = search_rate["roomId"], search_rate["rateId"]
    s_occ = search_rate["roomCriteria"]["adultCount"]

    for log_type in ("Packages", "PreBooking"):
        body = built[log_type]["httpResponse"]["body"]
        assert body["roomCriteria"]["adultCount"] == s_occ, f"{log_type} envelope occupancy"
        for rate in body["roomRates"]:
            assert rate["roomId"] == s_room, f"{log_type} roomId not linked to Search"
            assert rate["rateId"] == s_rate, f"{log_type} rateId not linked to Search"
            assert rate["roomCriteria"]["adultCount"] == s_occ, f"{log_type} rate occupancy"

    assert built["PreBooking"]["httpResponse"]["body"]["productCandidate"] == {
        "roomId": s_room,
        "rateId": s_rate,
    }


def test_chc_get_order_forced_confirmed():
    spec = PackageSpec(count=1, room_basis="RO", prices=[100], refundable=[True])
    built = {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(_chc_request(spec))}

    reservations = built["GetOrder"]["httpResponse"]["body"]["reservations"]
    assert reservations
    for reservation in reservations:
        assert reservation["status"] == "Confirmed"
        assert reservation["result"] == "Successful"


def test_build_chc_search_trims_to_target_hotel_and_applies_dates():
    spec = PackageSpec(count=2, room_basis="RO", prices=[100, 200], refundable=[True, True])
    built = {b.log_type: b.expectation for b in ScenarioEngine().build_expectations(_chc_request(spec))}

    hotels = built["Search"]["httpResponse"]["body"]["availHotels"]
    assert len(hotels) == 1
    assert hotels[0]["hotelId"] == "GB999"
    assert len(hotels[0]["availRoomRates"]) == 2
    assert hotels[0]["stayRange"] == {"checkin": "2026-09-01", "checkout": "2026-09-03"}
