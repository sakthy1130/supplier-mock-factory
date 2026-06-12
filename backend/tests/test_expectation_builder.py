from app.ingest.expectation_builder import (
    apply_aligned_derby_res_ids_for_booking_and_get_order,
    build_expectation,
    canonical_log_type,
    extract_request_payload_for_mock,
    extract_response_body_payload,
    is_target_log_type,
    resolve_http_path_and_method,
)
from app.ingest.expectation_builder import PendingExpectation


def test_canonical_log_type_aliases():
    assert canonical_log_type("Prebooking") == "PreBooking"
    assert canonical_log_type("search") == "Search"
    assert canonical_log_type("CancelOrder") == "CancelOrder"
    assert canonical_log_type("GetOrderResponse") == "GetOrder"
    assert canonical_log_type("CancelBooking") == "CancelOrder"
    assert canonical_log_type("PackagesResponse") is None


def test_is_target_log_type():
    assert is_target_log_type("Packages")
    assert not is_target_log_type("PackagesResponse")


def test_extract_response_body_payload_prefers_nested_body():
    full = {
        "response": {
            "headers": {"Date": "today"},
            "body": {"hotels": [{"hotelId": "1"}]},
        }
    }
    assert extract_response_body_payload(full) == {"hotels": [{"hotelId": "1"}]}


def test_extract_request_payload_strips_header_from_matcher():
    full = {
        "request": {
            "method": "POST",
            "url": "https://mock/hotel-api/1.0/hotels",
            "body": {
                "header": {"token": "abc"},
                "stayRange": {"checkIn": "2026-01-01"},
            },
        }
    }
    payload = extract_request_payload_for_mock(full)
    expectation = build_expectation("/hotel-api/1.0/hotels", "POST", payload, {"ok": True}, 200)
    assert "body" not in expectation["httpRequest"]


def test_resolve_http_path_from_request_url():
    list_row = {"logType": "Search", "source": "hotel-connectivity-hbs-adapter"}
    full = {
        "request": {
            "method": "POST",
            "url": "https://supplier.example.com/hotel-api/1.0/hotels",
            "body": {"hotels": []},
        },
        "response": {"body": {"hotels": []}},
    }
    http = resolve_http_path_and_method(list_row, full)
    assert http.path == "/hotel-api/1.0/hotels"
    assert http.method == "POST"


def test_apply_aligned_derby_res_ids():
    booking = build_expectation(
        "/book",
        "POST",
        None,
        {"reservationIds": {"distributorResId": "D1", "derbyResId": "OLD1"}},
        200,
    )
    get_order = build_expectation(
        "/order",
        "POST",
        None,
        {
            "reservations": [
                {
                    "status": "Confirmed",
                    "reservationIds": {"distributorResId": "D1", "derbyResId": "OLD2"},
                }
            ]
        },
        200,
    )
    pending = [
        PendingExpectation(expectation=booking, log_type="Booking"),
        PendingExpectation(expectation=get_order, log_type="GetOrder"),
    ]
    apply_aligned_derby_res_ids_for_booking_and_get_order(pending)

    booking_id = booking["httpResponse"]["body"]["reservationIds"]["derbyResId"]
    get_order_id = get_order["httpResponse"]["body"]["reservations"][0]["reservationIds"]["derbyResId"]
    assert booking_id == get_order_id
    assert booking_id != "OLD1"
    assert booking_id != "OLD2"
