"""Per-package booking-flow selection: engine gating, registration guard,
plugin linkage into Booking/GetOrder, and core select_package extraction."""

from __future__ import annotations

import pytest

from app.core.booking_id_injector import BOOKING_FLOW_LOG_TYPES, BookingIdInjector
from app.core.mock_registration import _inject_and_register_supplier
from app.core.scenario_engine import BuiltExpectation, ScenarioEngine, TEMPLATES_DIR
from app.integrations.core_app import (
    _build_passengers,
    _extract_order_price,
    _extract_order_status,
    _extract_segment_id,
    _package_total,
    _select_package,
)
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierCode, SupplierScenario

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Booking" / "v1.json").exists(),
    reason="Supplier templates not available",
)


def _request(code: str, booking_index):
    spec = PackageSpec(
        count=3,
        room_basis=["RO", "BB", "HB"],
        room_names=["Std Room", "Deluxe Room", "Suite Room"],
        supplier_currency="SAR",
        prices=[100.0, 222.0, 333.0],
        refundable=[True, False, True],
        booking_package_index=booking_index,
    )
    return ScenarioRequest(
        namespace="qa-booking-flow",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={code: "156652"},
        suppliers=[SupplierScenario(code=SupplierCode(code), packages=spec, contract_currency="USD")],
    )


def _built_by_type(code: str, booking_index):
    built = ScenarioEngine().build_expectations(_request(code, booking_index))
    return {item.log_type: item.expectation for item in built}


# --- model validator ------------------------------------------------------


def test_booking_package_index_out_of_range_rejected():
    with pytest.raises(ValueError):
        PackageSpec(count=2, room_basis="RO", prices=[100.0, 200.0], booking_package_index=2)


# --- engine gating --------------------------------------------------------


@pytest.mark.parametrize("code", ["HBS", "EXP", "EXT"])
def test_no_booking_flow_when_index_none(code):
    by_type = _built_by_type(code, None)
    assert not (BOOKING_FLOW_LOG_TYPES & set(by_type))
    assert "Packages" in by_type and "Search" in by_type


@pytest.mark.parametrize("code", ["HBS", "EXP", "EXT"])
def test_booking_flow_built_when_index_set(code):
    by_type = _built_by_type(code, 0)
    assert "Booking" in by_type
    assert "GetOrder" in by_type


# --- plugin linkage to the selected package -------------------------------


def test_hbs_booking_reflects_selected_package():
    by_type = _built_by_type("HBS", 1)  # price 222, BB, Deluxe Room
    for log_type, confirmed in (("Booking", True), ("GetOrder", True), ("CancelOrder", False)):
        booking = by_type[log_type]["httpResponse"]["body"]["booking"]
        rate = booking["hotel"]["rooms"][0]["rates"][0]
        assert rate["boardCode"] == "BB"
        assert booking["hotel"]["rooms"][0]["name"] == "Deluxe Room"
        if confirmed:
            assert rate["net"] == "222.0"
            assert booking["status"] == "CONFIRMED"


def test_exp_get_order_reflects_selected_package():
    by_type = _built_by_type("EXP", 1)  # price 222, refundable False
    body = by_type["GetOrder"]["httpResponse"]["body"]
    rate = body["rooms"][0]["rate"]
    assert rate["refundable"] is False
    total = rate["pricing"]["totals"]["inclusive"]["billable_currency"]["value"]
    assert abs(float(total) - 222.0) < 0.01


def test_ext_booking_reflects_selected_package():
    by_type = _built_by_type("EXT", 1)  # price 222, BB, Deluxe Room
    # Confirm uses the real EXT shape: reservation wrapped under body.body
    # (bookingId/status/price live there; no board/roomName on confirm).
    # Both confirm and getOrder use the real EXT shape: booking wrapped under
    # body.body (bookingId/status/price live there).
    for log_type in ("Booking", "GetOrder"):
        inner = by_type[log_type]["httpResponse"]["body"]["body"]
        assert float(inner["totalPrice"]) == 222.0
        assert float(inner["netPrice"]) == 222.0
        assert inner["status"] == "BOOKED"


# --- registration guard ---------------------------------------------------


class _FakeMockClient:
    def __init__(self):
        self.registered: list[dict] = []

    async def register_expectations(self, expectations):
        self.registered.extend(expectations)
        return len(expectations)


@pytest.mark.asyncio
async def test_registration_skips_injection_without_booking():
    client = _FakeMockClient()
    items = [
        BuiltExpectation("HBS", "Search", {"id": "s", "httpResponse": {"body": {}}}),
        BuiltExpectation("HBS", "Packages", {"id": "p", "httpResponse": {"body": {}}}),
    ]
    new_id = await _inject_and_register_supplier(BookingIdInjector(), client, "HBS", items, None)
    assert new_id == ""
    assert len(client.registered) == 2


# --- core select_package / order extraction -------------------------------


def _packages_poll():
    # netPrice = the UI-entered price; total = net + markup.
    return {
        "packagesResult": {
            "packages": [
                {
                    "packageId": "PKG-A",
                    "rooms": [{"roomId": "R1", "roomBasis": "RO", "roomName": {"en": "Std Room"}}],
                    "packageRateInfo": {"total": 118.0, "netPrice": 100.0},
                },
                {
                    "packageId": "PKG-B",
                    "rooms": [{"roomId": "R2", "roomBasis": "BB", "roomName": {"en": "Deluxe Room"}}],
                    "packageRateInfo": {"total": 262.0, "netPrice": 222.0},
                },
            ]
        }
    }


def test_select_package_matches_on_board_and_room():
    package = _select_package(_packages_poll(), {"board": "BB", "room_name": "Deluxe Room", "price": 222.0})
    assert package["packageId"] == "PKG-B"


def test_select_package_matches_on_net_price_under_markup():
    # Only price given; must match against netPrice (222), not total (262).
    package = _select_package(_packages_poll(), {"price": 222.0})
    assert package["packageId"] == "PKG-B"


def test_select_package_single_package_returned():
    poll = {"packagesResult": {"packages": [{"packageId": "ONLY", "rooms": [{"roomId": "R1"}]}]}}
    assert _select_package(poll, {"board": "ZZ"})["packageId"] == "ONLY"


def test_booking_price_uses_package_total_not_net():
    package = _select_package(_packages_poll(), {"price": 222.0})
    assert _package_total(package) == 262.0  # bookingPrice must be the final total


def test_build_passengers_two_adults_lead_matches_first_paxid():
    package = {"rooms": [{"roomId": "R2", "numberOfAdults": 2}]}
    passengers, lead_pax_id = _build_passengers(package)
    assert len(passengers) == 2
    assert passengers[0]["paxId"] == lead_pax_id
    for p in passengers:
        assert p["roomId"] == "R2"
        assert p["personDetails"]["type"] == 0
        assert set(p["personDetails"]["name"]) == {"namePrefix", "givenName", "surname", "middleName"}
        assert set(p["address"]) == {"addressLine", "cityName", "countryName", "postalCode"}
        assert "dateOfBirth" not in p["personDetails"]


def test_build_passengers_includes_child_for_kid_age():
    package = {"rooms": [{"roomId": "R1", "numberOfAdults": 1, "kidsAges": [7]}]}
    passengers, _ = _build_passengers(package)
    assert len(passengers) == 2
    child = passengers[-1]
    assert child["personDetails"]["type"] == 1
    assert child["personDetails"]["age"] == 7


def test_extract_order_fields():
    order = {
        "orderResults": {
            "orderDetails": {
                "orderStatus": "OK",
                "segments": [{"price": {"total": 262.0}}],
            }
        }
    }
    assert _extract_order_status(order) == "OK"
    assert _extract_order_price(order) == 262.0


def test_extract_order_price_array_in_string():
    order = {"orderResults": {"orderDetails": {"segments": {"price": {"total": "[262.0]"}}}}}
    assert _extract_order_price(order) == 262.0


def test_extract_segment_id():
    booking_poll = {"bookingResult": {"bookingResults": [{"segmentId": "SEG-1"}]}}
    assert _extract_segment_id(booking_poll) == "SEG-1"


# --- booking poll (success + failure-code surfacing) ----------------------


@pytest.mark.asyncio
async def test_poll_booking_surfaces_error_code():
    from app.integrations.core_app import CoreAppClient, CoreAppError

    client = CoreAppClient()

    async def fake(path, *, method, api_key, payload=None):
        return {
            "pollingStatus": "COMPLETED_WITH_FAILURE",
            "totalResults": 0,
            "errors": [{"errorCode": "E3023.4"}],
        }

    client._request_json = fake  # type: ignore[method-assign]
    with pytest.raises(CoreAppError) as exc:
        await client._poll_booking("b1", api_key="k", trace=[])
    assert "E3023.4" in str(exc.value)


@pytest.mark.asyncio
async def test_poll_booking_success_requires_total_results():
    from app.integrations.core_app import CoreAppClient

    client = CoreAppClient()

    async def fake(path, *, method, api_key, payload=None):
        return {
            "pollingStatus": "COMPLETED_SUCCESSFULLY",
            "totalResults": 1,
            "bookingResult": {"bookingResults": [{"segmentId": "S1"}]},
        }

    client._request_json = fake  # type: ignore[method-assign]
    body = await client._poll_booking("b1", api_key="k", trace=[])
    assert _extract_segment_id(body) == "S1"
