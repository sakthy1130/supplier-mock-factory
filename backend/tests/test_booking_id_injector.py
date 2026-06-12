import copy
import json
from pathlib import Path

import pytest

from app.core.booking_id_injector import BookingIdInjector
from app.core.scenario_engine import REPO_ROOT

TEMPLATES_DIR = REPO_ROOT / "templates"


def _load_supplier_templates(supplier: str, log_types: list[str]) -> dict[str, dict]:
    result = {}
    for log_type in log_types:
        path = TEMPLATES_DIR / supplier / log_type / "v1.json"
        result[log_type] = json.loads(path.read_text(encoding="utf-8"))
    return result


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Booking" / "v1.json").exists(),
    reason="HBS booking templates not ingested",
)
def test_hbs_booking_id_injected_across_book_get_cancel():
    injector = BookingIdInjector()
    expectations = _load_supplier_templates("HBS", ["Booking", "GetOrder", "CancelOrder"])
    field_map = {
        "paths": {
            "booking_id": [
                "httpResponse.body.booking.reference",
            ]
        }
    }

    new_id = injector.inject(expectations, "HBS", field_map, booking_id="148-9999999")

    assert new_id == "148-9999999"
    assert expectations["Booking"]["httpResponse"]["body"]["booking"]["reference"] == new_id
    assert expectations["GetOrder"]["httpResponse"]["body"]["booking"]["reference"] == new_id
    assert expectations["CancelOrder"]["httpResponse"]["body"]["booking"]["reference"] == new_id
    assert new_id in expectations["GetOrder"]["httpRequest"]["path"]
    assert new_id in expectations["CancelOrder"]["httpRequest"]["path"]


def test_hbs_get_order_path_appends_booking_id_for_canonical_mock_path():
    injector = BookingIdInjector()
    expectations = {
        "Booking": {
            "httpResponse": {"body": {"booking": {"reference": "148-6069492"}}},
            "httpRequest": {"path": "/hotel-api/1.2/bookings/booking"},
        },
        "GetOrder": {
            "httpResponse": {"body": {"booking": {"reference": "148-6069492"}}},
            "httpRequest": {"path": "/hotel-api/1.2/bookings/GetOrderBooking"},
        },
    }
    field_map = {"paths": {"booking_id": ["httpResponse.body.booking.reference"]}}

    new_id = injector.inject(expectations, "HBS", field_map, booking_id="148-9999999")

    assert expectations["GetOrder"]["httpRequest"]["path"] == (
        f"/hotel-api/1.2/bookings/GetOrderBooking/{new_id}"
    )


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "EXP" / "Booking" / "v1.json").exists(),
    reason="EXP booking templates not ingested",
)
def test_exp_booking_id_injected_across_book_get_cancel():
    injector = BookingIdInjector()
    expectations = _load_supplier_templates("EXP", ["Booking", "GetOrder", "CancelOrder"])
    field_map = {"paths": {"booking_id": ["httpResponse.body.itinerary_id"]}}

    new_id = injector.inject(expectations, "EXP", field_map)

    assert new_id
    assert expectations["Booking"]["httpResponse"]["body"]["itinerary_id"] == new_id
    assert expectations["GetOrder"]["httpResponse"]["body"]["itinerary_id"] == new_id
    assert new_id in expectations["GetOrder"]["httpRequest"]["path"]
    assert new_id in expectations["CancelOrder"]["httpRequest"]["path"]


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "RHK" / "Booking" / "v1.json").exists(),
    reason="RHK booking templates not ingested",
)
def test_rhk_booking_id_injected_across_book_get_cancel():
    injector = BookingIdInjector()
    expectations = _load_supplier_templates("RHK", ["Booking", "GetOrder", "CancelOrder"])
    field_map = {"paths": {"booking_id": []}}

    new_id = injector.inject(expectations, "RHK", field_map, booking_id="smf-test-order-abc123")

    assert new_id == "smf-test-order-abc123"
    assert (
        expectations["Booking"]["httpResponse"]["body"]["debug"]["request"]["partner"]["partner_order_id"]
        == new_id
    )
    assert expectations["GetOrder"]["httpResponse"]["body"]["data"]["orders"][0]["order_id"] == new_id
    assert (
        expectations["CancelOrder"]["httpResponse"]["body"]["debug"]["request"]["partner_order_id"]
        == new_id
    )


def test_hbs_booking_id_paths_still_use_field_map_not_rhk_override():
    injector = BookingIdInjector()
    field_map = {"paths": {"booking_id": ["httpResponse.body.booking.reference"]}}
    paths = injector._booking_id_paths("HBS", "Booking", field_map)
    assert paths == ["httpResponse.body.booking.reference"]
    assert injector._booking_id_paths("RHK", "Booking", field_map) != paths


def test_generate_booking_id_preserves_hbs_prefix():
    injector = BookingIdInjector()
    generated = injector.generate_booking_id("HBS", "148-6069492")
    assert generated.startswith("148-")
    assert generated != "148-6069492"


def test_inject_generates_unique_ids_for_repeated_calls():
    injector = BookingIdInjector()
    booking = {
        "httpResponse": {"body": {"booking": {"reference": "148-6069492"}}},
        "httpRequest": {"path": "/hotel-api/1.2/bookings"},
    }
    get_order = {
        "httpResponse": {"body": {"booking": {"reference": "148-6069492"}}},
        "httpRequest": {"path": "/hotel-api/1.2/bookings/148-6069492"},
    }
    field_map = {"paths": {"booking_id": ["httpResponse.body.booking.reference"]}}

    first = copy.deepcopy({"Booking": booking, "GetOrder": get_order})
    second = copy.deepcopy({"Booking": booking, "GetOrder": get_order})
    id_one = injector.inject(first, "HBS", field_map)
    id_two = injector.inject(second, "HBS", field_map)
    assert id_one != id_two
