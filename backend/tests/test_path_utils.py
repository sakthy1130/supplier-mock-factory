from app.core.path_utils import get_by_path, replace_string_values, set_by_path


def test_get_and_set_by_path_with_indexes():
    root = {"httpResponse": {"body": {"booking": {"reference": "148-1"}}}}
    assert get_by_path(root, "httpResponse.body.booking.reference") == "148-1"
    set_by_path(root, "httpResponse.body.booking.reference", "148-2")
    assert root["httpResponse"]["body"]["booking"]["reference"] == "148-2"


def test_replace_string_values_deep():
    root = {
        "httpRequest": {
            "path": "/bookings/148-6069492",
            "body": {"json": {"url": "https://example/bookings/148-6069492"}},
        }
    }
    replace_string_values(root, "148-6069492", "148-9999999")
    assert root["httpRequest"]["path"] == "/bookings/148-9999999"
    assert "148-9999999" in root["httpRequest"]["body"]["json"]["url"]
