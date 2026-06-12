from app.core.expectation_utils import finalize_expectation_for_register
from app.core.hbs_paths import build_hbs_contract_opt_urls, build_hbs_mock_path
from app.core.mock_urls import build_mock_opt_urls


def test_build_hbs_mock_paths_use_canonical_roots_and_suffixes():
    assert build_hbs_mock_path("Search") == "/hotel-api/1.0/hotels/search"
    assert build_hbs_mock_path("Packages") == "/hotel-api/1.0/hotels/package/availability"
    assert build_hbs_mock_path("PreBooking") == "/hotel-api/1.0/checkrates/preBooking"
    assert build_hbs_mock_path("Booking") == "/hotel-api/1.2/bookings/booking"
    assert build_hbs_mock_path("GetOrder") == "/hotel-api/1.2/bookings/GetOrderBooking"
    assert build_hbs_mock_path("CancelOrder") == "/hotel-api/1.2/bookings/cancelBooking"


def test_build_hbs_contract_opt_urls():
    base = "http://mockserver-staging.tajawal.io"
    opt = build_hbs_contract_opt_urls(base)
    assert opt["searchUrl"] == f"{base}/hotel-api/1.0/hotels/search"
    assert opt["availabilityUrl"] == f"{base}/hotel-api/1.0/hotels/package/availability"
    assert opt["prebookingUrl"] == f"{base}/hotel-api/1.0/checkrates/preBooking"
    assert opt["bookingUrl"] == f"{base}/hotel-api/1.2/bookings/booking"
    assert opt["orderUrl"] == f"{base}/hotel-api/1.2/bookings/GetOrderBooking"
    assert opt["cancelBookingUrl"] == f"{base}/hotel-api/1.2/bookings/cancelBooking"
    assert opt["availabilityTimeoutSeconds"] == "50"
    assert opt["paymentType"] == "AT_WEB"
    assert opt["packagingEnabled"] is False
    assert opt["mockServerUrl"] == f"{base}/"


def test_build_mock_opt_urls_hbs_ignores_extracted_paths():
    opt = build_mock_opt_urls(
        "http://mock.example",
        {"Search": "/hotel-api/1.2/hotels", "Booking": "/hotel-api/1.2/bookings"},
        supplier_code="HBS",
    )
    assert opt["searchUrl"].endswith("/hotel-api/1.0/hotels/search")
    assert opt["prebookingUrl"].endswith("/hotel-api/1.0/checkrates/preBooking")


def test_finalize_expectation_applies_hbs_mock_path():
    expectation = {
        "httpRequest": {
            "path": "/hotel-api/1.2/hotels",
            "method": "POST",
            "body": {"type": "JSON", "json": {}},
        },
        "priority": 1000,
    }
    result = finalize_expectation_for_register(expectation, "qa-001", "HBS", "Search")
    assert result["httpRequest"]["path"] == "/hotel-api/1.0/hotels/search"
    assert "body" not in result["httpRequest"]
