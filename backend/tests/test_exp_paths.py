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
