from app.core.exp_paths import (
    apply_namespace_to_price_check_hrefs,
    build_exp_price_check_href,
    extract_price_check_token,
)


def test_build_exp_price_check_href_preserves_token():
    href = build_exp_price_check_href("2001358", "326827168", "402940109", "token=abc123")
    assert href == "/v3/properties/2001358/rooms/326827168/rates/402940109?token=abc123"


def test_extract_price_check_token():
    assert extract_price_check_token("/v3/properties/1/rooms/2/rates/3?token=xyz") == "token=xyz"


def _expectation(href: str) -> dict:
    return {
        "httpResponse": {
            "body": [
                {
                    "rooms": [
                        {
                            "rates": [
                                {
                                    "links": {"price_check": {"href": href}},
                                    "bed_groups": {
                                        "bg1": {"links": {"price_check": {"href": href}}}
                                    },
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }


def test_price_check_href_gets_namespace_prefix():
    href = "/v3/properties/123/rooms/456/rates/789?token=abc"
    expectation = _expectation(href)

    apply_namespace_to_price_check_hrefs(expectation, "qa-exp-001")

    rate = expectation["httpResponse"]["body"][0]["rooms"][0]["rates"][0]
    expected = "/qa-exp-001/v3/properties/123/rooms/456/rates/789?token=abc"
    assert rate["links"]["price_check"]["href"] == expected
    assert rate["bed_groups"]["bg1"]["links"]["price_check"]["href"] == expected


def test_price_check_href_prefix_is_idempotent():
    expectation = _expectation("/v3/properties/123/rooms/456/rates/789")

    apply_namespace_to_price_check_hrefs(expectation, "qa-exp-001")
    apply_namespace_to_price_check_hrefs(expectation, "qa-exp-001")

    rate = expectation["httpResponse"]["body"][0]["rooms"][0]["rates"][0]
    assert rate["links"]["price_check"]["href"] == "/qa-exp-001/v3/properties/123/rooms/456/rates/789"


def test_absolute_price_check_href_is_left_alone():
    """A full URL (not the canonical relative path) is not ours to rewrite."""
    href = "https://api.ean.com/v3/properties/123/rooms/456/rates/789"
    expectation = _expectation(href)

    apply_namespace_to_price_check_hrefs(expectation, "qa-exp-001")

    rate = expectation["httpResponse"]["body"][0]["rooms"][0]["rates"][0]
    assert rate["links"]["price_check"]["href"] == href


def test_booking_retrieve_href_is_namespaced():
    """The Booking response's links.retrieve is how the adapter finds GetOrder.

    Left un-prefixed, the adapter follows /v3/itineraries/{id}, MockServer has no such
    expectation (the mock is at /{namespace}/v3/itineraries/{id}), and the core reports
    E3027.3 "unexpected or unhandled get order response". Observed on a real staging run:
    MockServer logged GET /v3/itineraries/2566596970695 -> 404 right before the error.
    """
    from app.core.exp_paths import apply_namespace_to_response_hrefs

    expectation = {
        "httpResponse": {
            "body": {"links": {"retrieve": {"method": "GET", "href": "/v3/itineraries/123?token=t"}}}
        }
    }
    apply_namespace_to_response_hrefs(expectation, "/qa-ns")
    assert (
        expectation["httpResponse"]["body"]["links"]["retrieve"]["href"]
        == "/qa-ns/v3/itineraries/123?token=t"
    )


def test_absolute_hrefs_are_left_alone():
    """GetOrder's conversations block carries an absolute supplier URL — prefixing it
    would corrupt it into a nonsense path."""
    from app.core.exp_paths import apply_namespace_to_response_hrefs

    expectation = {
        "httpResponse": {
            "body": {"links": {"property": {"href": "https://www.example.com?key=123abd456"}}}
        }
    }
    apply_namespace_to_response_hrefs(expectation, "/qa-ns")
    assert (
        expectation["httpResponse"]["body"]["links"]["property"]["href"]
        == "https://www.example.com?key=123abd456"
    )


def test_every_relative_link_type_is_namespaced_not_just_price_check():
    """book / additional_rates / payment_options / recommendations had the same hole."""
    from app.core.exp_paths import apply_namespace_to_response_hrefs

    links = {
        "book": {"href": "/v3/itineraries?token=t"},
        "additional_rates": {"href": "/v3/properties/1/availability?token=t"},
        "payment_options": {"href": "/v3/properties/1/payment-options?token=t"},
        "recommendations": {"href": "/v3/properties/availability?token=t"},
        "price_check": {"href": "/v3/properties/1/rooms/2/rates/3?token=t"},
    }
    expectation = {"httpResponse": {"body": {"links": links}}}
    apply_namespace_to_response_hrefs(expectation, "/qa-ns")
    for name, link in expectation["httpResponse"]["body"]["links"].items():
        assert link["href"].startswith("/qa-ns/v3/"), f"{name} not namespaced: {link['href']}"


def test_exp_getorder_stay_dates_follow_the_scenario():
    """EXP GetOrder spells the stay lowercase on rooms[] — "checkin"/"checkout".

    mutate_dates only handled camelCase keys and URL query params, so the retrieved
    order kept the captured template's stay (2026-08-13 -> 18) whatever was booked.
    """
    import json
    from pathlib import Path
    from app.plugins.exp import ExpMockPlugin

    template = json.loads(
        (Path(__file__).resolve().parents[2] / "templates/EXP/GetOrder/v1.json").read_text()
    )
    out = ExpMockPlugin().mutate_dates(template, "2026-09-01", "2026-09-03")
    for room in out["httpResponse"]["body"]["rooms"]:
        assert room["checkin"] == "2026-09-01"
        assert room["checkout"] == "2026-09-03"


def test_exp_getorder_rooms_carry_a_cancel_link():
    """The adapter reads the cancel URL off the retrieved room.

    The template was captured from a CANCELLED itinerary, where Expedia omits
    links.cancel entirely, and the adapter logged "Failed to get cancel booking url
    from supplier". The link must be present and must point at the CancelOrder mock.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    get_order = json.loads((root / "templates/EXP/GetOrder/v1.json").read_text())
    cancel_path = json.loads((root / "templates/EXP/CancelOrder/v1.json").read_text())
    expected = cancel_path["httpRequest"]["path"]

    rooms = get_order["httpResponse"]["body"]["rooms"]
    assert rooms, "GetOrder template has no rooms"
    for room in rooms:
        href = room.get("links", {}).get("cancel", {}).get("href")
        assert href == expected, f"cancel href {href!r} does not match CancelOrder mock {expected!r}"
