from app.core.expectation_utils import finalize_expectation_for_register, strip_http_request_matchers


def test_strip_http_request_matchers_removes_body_and_headers():
    expectation = {
        "httpRequest": {
            "path": "/test",
            "method": "POST",
            "headers": {"X-Mock-Scenario-Id": ["ns"]},
            "body": {"type": "JSON", "json": {"hotel": 1}},
        },
        "priority": 1000,
    }
    result = strip_http_request_matchers(expectation)
    assert "body" not in result["httpRequest"]
    assert "headers" not in result["httpRequest"]
    assert result["httpRequest"]["path"] == "/test"


def test_finalize_expectation_for_register_sets_id_and_strips_matchers():
    expectation = {
        "httpRequest": {
            "path": "/test",
            "method": "POST",
            "headers": {"Authorization": ["token"]},
            "body": {"type": "JSON", "json": {}},
        },
        "priority": 1000,
    }
    result = finalize_expectation_for_register(expectation, "qa-001", "EXP", "Search")
    assert result["id"] == "smf-qa-001-exp-search"
    assert "headers" not in result["httpRequest"]
    assert "body" not in result["httpRequest"]
