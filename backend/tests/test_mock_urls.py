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
    # HBS flows through the same generic branch as RHK/CHC/EXT — opt URLs are built
    # from whatever path was actually registered (already namespace-prefixed in
    # production), not reconstructed independently from the canonical roots.
    opt = build_mock_opt_urls(
        "http://mockserver-staging.tajawal.io",
        {
            "Search": "/qa-001/hotel-api/1.0/hotels/search",
            "Packages": "/qa-001/hotel-api/1.0/hotels/package/availability",
            "Booking": "/qa-001/hotel-api/1.2/bookings/booking",
            "GetOrder": "/qa-001/hotel-api/1.2/bookings/GetOrderBooking",
            "CancelOrder": "/qa-001/hotel-api/1.2/bookings/cancelBooking",
        },
        supplier_code="HBS",
    )
    base = "http://mockserver-staging.tajawal.io"
    assert opt["searchUrl"] == f"{base}/qa-001/hotel-api/1.0/hotels/search"
    assert opt["availabilityUrl"] == f"{base}/qa-001/hotel-api/1.0/hotels/package/availability"
    assert opt["bookingUrl"] == f"{base}/qa-001/hotel-api/1.2/bookings/booking"
    assert opt["orderUrl"] == f"{base}/qa-001/hotel-api/1.2/bookings/GetOrderBooking"
    assert opt["cancelBookingUrl"] == f"{base}/qa-001/hotel-api/1.2/bookings/cancelBooking"


def test_hbs_order_url_strips_booking_id_suffix():
    # After booking-id injection the GetOrder mock path carries the id
    # (.../GetOrderBooking/<id>). The contract orderUrl must be the base
    # (.../GetOrderBooking) because the HBS adapter appends the id itself —
    # otherwise the id doubles and getOrder 404s (E1011.1).
    opt = build_mock_opt_urls(
        "http://mockserver-staging.tajawal.io",
        {
            "Booking": "/qa-001/hotel-api/1.2/bookings/booking",
            "GetOrder": "/qa-001/hotel-api/1.2/bookings/GetOrderBooking/148-4285117",
            "CancelOrder": "/qa-001/hotel-api/1.2/bookings/cancelBooking",
        },
        supplier_code="HBS",
    )
    base = "http://mockserver-staging.tajawal.io"
    assert opt["orderUrl"] == f"{base}/qa-001/hotel-api/1.2/bookings/GetOrderBooking"
    # cancel/booking must be untouched
    assert opt["cancelBookingUrl"] == f"{base}/qa-001/hotel-api/1.2/bookings/cancelBooking"


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
    # Standard fields are ALSO set (pointed at the mock) so core's "Booking url is
    # blocked" (E2002) check — which reads bookingUrl, not overrideBookingUrl —
    # doesn't reject the cloned reference's real-Expedia URL.
    assert opt["bookingUrl"] == f"{base}/v3/itineraries"
    assert opt["searchUrl"] == f"{base}/v3/properties/availability"


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
    # Standard bookingUrl must also point at the mock (E2002 block check).
    assert opt["bookingUrl"] == "http://mock.example/v3/itineraries"
    assert opt["searchUrl"] == "http://mock.example/v3/properties/availability"
