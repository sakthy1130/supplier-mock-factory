"""Templates must never be a captured failure.

A supplier call that failed upstream is logged as an error envelope — exception text,
the upstream status, an empty body — and ingest used to write that envelope as the
template. The resulting mock answers 200 with a stack trace, which looks healthy in
MockServer while the adapter cannot deserialize it: booking-service rejects the
GetOrder as invalid and core polls for the order until the caller times out. That is
what templates/HIL/GetOrder/v1.json held.
"""

import json
from pathlib import Path

import pytest

from app.ingest.expectation_builder import is_error_envelope_payload

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
TEMPLATE_FILES = sorted(TEMPLATES_DIR.glob("*/*/v1.json"))


def test_templates_exist():
    assert TEMPLATE_FILES, f"no templates found under {TEMPLATES_DIR}"


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=lambda p: f"{p.parts[-3]}/{p.parts[-2]}")
def test_no_template_replays_a_failed_supplier_call(path):
    body = json.loads(path.read_text(encoding="utf-8"))["httpResponse"]["body"]
    assert not is_error_envelope_payload(body), (
        f"{path.parts[-3]}/{path.parts[-2]} was ingested from a failed supplier call — "
        "re-ingest from a SID whose call succeeded"
    )


def test_hil_get_order_is_a_derby_reservation_detail():
    """The shape the Derby BTS adapter deserializes, and the ids booking-id injection
    rewrites (field-maps/HIL.json points at httpResponse.body.reservationIds.*, and the
    reservation node carries its own copy for the adapter)."""
    body = json.loads(
        (TEMPLATES_DIR / "HIL" / "GetOrder" / "v1.json").read_text(encoding="utf-8")
    )["httpResponse"]["body"]

    assert body["header"]["supplierId"] == "HILTON"
    reservation = body["reservations"][0]
    assert reservation["status"] == "Confirmed"
    assert set(reservation["reservationIds"]) == {
        "distributorResId",
        "derbyResId",
        "supplierResId",
    }
    rate = reservation["roomRates"][0]
    # Derby declares List<Double> for both amount fields, and refundability is read off
    # cancelPolicy.code rather than a boolean.
    assert isinstance(rate["amountBeforeTax"], list) and rate["amountBeforeTax"]
    assert isinstance(rate["amountAfterTax"], list) and rate["amountAfterTax"]
    assert rate["cancelPolicy"]["code"]


def test_hil_get_order_ids_match_the_booking_template():
    """Booking-id injection takes the id from Booking and replaces that literal across
    the booking-flow mocks, so a GetOrder carrying different ids would keep the
    template's stale ones and describe someone else's reservation."""
    booking = json.loads(
        (TEMPLATES_DIR / "HIL" / "Booking" / "v1.json").read_text(encoding="utf-8")
    )["httpResponse"]["body"]
    get_order = json.loads(
        (TEMPLATES_DIR / "HIL" / "GetOrder" / "v1.json").read_text(encoding="utf-8")
    )["httpResponse"]["body"]

    assert get_order["reservations"][0]["reservationIds"] == booking["reservationIds"]
