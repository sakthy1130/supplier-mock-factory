from app.core.exp_paths import build_exp_price_check_href, extract_price_check_token


def test_build_exp_price_check_href_preserves_token():
    href = build_exp_price_check_href("2001358", "326827168", "402940109", "token=abc123")
    assert href == "/v3/properties/2001358/rooms/326827168/rates/402940109?token=abc123"


def test_extract_price_check_token():
    assert extract_price_check_token("/v3/properties/1/rooms/2/rates/3?token=xyz") == "token=xyz"
