from app.core.expectation_utils import (
    finalize_expectation_for_register,
    strip_http_request_matchers,
    strip_response_framing_headers,
)


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


def test_strip_response_framing_headers_removes_stale_framing():
    expectation = {
        "httpResponse": {
            "statusCode": 200,
            "headers": {
                "content-type": ["application/json"],
                "Content-Length": ["9435"],
                "content-encoding": ["gzip"],
                "Transfer-Encoding": ["chunked"],
                "connection": ["keep-alive"],
                "server": ["EAN"],
            },
            "body": {"hotels": []},
        }
    }
    result = strip_response_framing_headers(expectation)
    headers = result["httpResponse"]["headers"]
    assert "content-type" in headers
    assert "server" in headers
    for gone in ("Content-Length", "content-encoding", "Transfer-Encoding", "connection"):
        assert gone not in headers


def test_finalize_strips_response_framing_headers():
    expectation = {
        "httpRequest": {"path": "/x", "method": "GET"},
        "httpResponse": {
            "statusCode": 200,
            "headers": {"content-length": ["9435"], "content-encoding": ["gzip"]},
            "body": {"hotels": []},
        },
        "priority": 1000,
    }
    result = finalize_expectation_for_register(expectation, "qa-001", "EXP", "Search")
    assert result["httpResponse"]["headers"] == {}
