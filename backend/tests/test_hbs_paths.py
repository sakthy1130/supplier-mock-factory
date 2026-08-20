from app.core.expectation_utils import finalize_expectation_for_register
from app.core.hbs_paths import build_hbs_mock_path
from app.core.mock_urls import build_mock_opt_urls


def test_build_hbs_mock_paths_use_canonical_roots_and_suffixes():
    assert build_hbs_mock_path("Search") == "/hotel-api/1.0/hotels/search"
    assert build_hbs_mock_path("Packages") == "/hotel-api/1.0/hotels/package/availability"
    assert build_hbs_mock_path("PreBooking") == "/hotel-api/1.0/checkrates/preBooking"
    assert build_hbs_mock_path("Booking") == "/hotel-api/1.2/bookings/booking"
    assert build_hbs_mock_path("GetOrder") == "/hotel-api/1.2/bookings/GetOrderBooking"
    assert build_hbs_mock_path("CancelOrder") == "/hotel-api/1.2/bookings/cancelBooking"


def test_build_mock_opt_urls_hbs_uses_extracted_paths():
    # HBS now flows through the same generic branch as RHK/CHC/EXT — contract opt
    # URLs are built from whatever path was actually registered (already namespaced),
    # not reconstructed independently from the canonical roots.
    opt = build_mock_opt_urls(
        "http://mock.example",
        {"Search": "/qa-001/hotel-api/1.0/hotels/search", "Booking": "/qa-001/hotel-api/1.2/bookings/booking"},
        supplier_code="HBS",
    )
    assert opt["searchUrl"] == "http://mock.example/qa-001/hotel-api/1.0/hotels/search"
    assert opt["bookingUrl"] == "http://mock.example/qa-001/hotel-api/1.2/bookings/booking"


def test_finalize_expectation_applies_hbs_mock_path_with_namespace_prefix():
    expectation = {
        "httpRequest": {
            "path": "/hotel-api/1.2/hotels",
            "method": "POST",
            "body": {"type": "JSON", "json": {}},
        },
        "priority": 1000,
    }
    result = finalize_expectation_for_register(expectation, "qa-001", "HBS", "Search")
    assert result["httpRequest"]["path"] == "/qa-001/hotel-api/1.0/hotels/search"
    assert "body" not in result["httpRequest"]
