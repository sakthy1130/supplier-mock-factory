from app.core.mock_urls import build_exp_override_opt_urls, build_mock_opt_urls, extract_paths_from_built
from app.core.scenario_engine import BuiltExpectation


def test_extract_paths_from_built():
    built = [
        BuiltExpectation(
            supplier_code="HBS",
            log_type="Search",
            expectation={"httpRequest": {"path": "/hotel-api/1.2/hotels"}},
        ),
        BuiltExpectation(
            supplier_code="HBS",
            log_type="Booking",
            expectation={"httpRequest": {"path": "/hotel-api/1.2/bookings"}},
        ),
    ]
    paths = extract_paths_from_built(built)
    assert paths["HBS"]["Search"] == "/hotel-api/1.2/hotels"
    assert paths["HBS"]["Booking"] == "/hotel-api/1.2/bookings"


def test_build_mock_opt_urls_maps_log_types_for_hbs():
    opt = build_mock_opt_urls(
        "http://mockserver-staging.tajawal.io",
        {
            "Search": "/hotel-api/1.2/hotels",
            "Packages": "/hotel-api/1.2/hotels",
            "Booking": "/hotel-api/1.2/bookings",
            "GetOrder": "/hotel-api/1.2/bookings/123",
            "CancelOrder": "/hotel-api/1.2/bookings/123",
        },
        supplier_code="HBS",
    )
    base = "http://mockserver-staging.tajawal.io"
    assert opt["searchUrl"] == f"{base}/hotel-api/1.0/hotels/search"
    assert opt["availabilityUrl"] == f"{base}/hotel-api/1.0/hotels/package/availability"
    assert opt["prebookingUrl"] == f"{base}/hotel-api/1.0/checkrates/preBooking"
    assert opt["bookingUrl"] == f"{base}/hotel-api/1.2/bookings/booking"
    assert opt["orderUrl"] == f"{base}/hotel-api/1.2/bookings/GetOrderBooking"
    assert opt["cancelBookingUrl"] == f"{base}/hotel-api/1.2/bookings/cancelBooking"


def test_build_exp_override_opt_urls():
    opt = build_exp_override_opt_urls(
        "http://mockserver-staging.tajawal.io",
        {
            "Search": "/v3/properties/availability",
            "Packages": "/v3/properties/1723385/availability",
            "Booking": "/v3/itineraries",
            "GetOrder": "/v3/itineraries/7556800480832",
            "CancelOrder": "/v3/itineraries/7556800480832/rooms/1",
        },
    )
    base = "http://mockserver-staging.tajawal.io"
    assert opt["overrideSearchUrl"] == f"{base}/v3/properties/availability"
    assert opt["overridePackagesUrl"] == f"{base}/v3/properties/1723385/availability"
    assert opt["overrideBookingUrl"] == f"{base}/v3/itineraries"
    assert opt["overrideRetrieveBookingUrl"] == f"{base}/v3/itineraries/7556800480832"
    assert opt["overrideCancelBookingUrl"] == f"{base}/v3/itineraries/7556800480832/rooms/1"
    assert "searchUrl" not in opt


def test_build_mock_opt_urls_exp_uses_overrides():
    paths = {
        "Search": "/v3/properties/availability",
        "Packages": "/v3/properties/1/availability",
        "Booking": "/v3/itineraries",
        "GetOrder": "/v3/itineraries/1",
        "CancelOrder": "/v3/itineraries/1/rooms/1",
    }
    opt = build_mock_opt_urls("http://mock.example", paths, supplier_code="EXP")
    assert "overrideSearchUrl" in opt
    assert "searchUrl" not in opt
