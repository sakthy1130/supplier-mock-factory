from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.core_app import CoreAppClient


class _Response:
    def __init__(self, payload, status_code=200, text="{}"):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_core_app_client_uses_get_for_packages_poll():
    client = AsyncMock()
    client.request = AsyncMock(
        side_effect=[
            _Response({"sId": "sid-1"}),
            _Response({"pollingStatus": "COMPLETED_SUCCESSFULLY", "searchResults": [{"hotelId": "1043546"}]}),
            _Response({"pId": "pid-1"}),
            _Response({"pollingStatus": "COMPLETED_SUCCESSFULLY"}),
        ]
    )

    core = CoreAppClient(client=client)
    core.settings.core_app_url = "http://core.example"

    result = await core.run_search_and_packages(
        api_key="api-key-1",
        check_in="2026-09-01",
        check_out="2026-09-03",
        hotel_id="1043546",
    )

    assert result.search_s_id == "sid-1"
    assert result.package_p_id == "pid-1"
    assert result.package_status == "COMPLETED_SUCCESSFULLY"
    assert len(result.logs) == 4
    assert result.logs[0]["step"] == "search"
    assert result.logs[0]["method"] == "POST"
    assert result.logs[1]["step"] == "search"
    assert result.logs[1]["method"] == "GET"
    assert result.logs[2]["step"] == "packages"
    assert result.logs[2]["method"] == "POST"
    assert result.logs[3]["step"] == "packages"
    assert result.logs[3]["method"] == "GET"

    methods = [call.args[0] for call in client.request.await_args_list]
    paths = [call.args[1] for call in client.request.await_args_list]
    assert methods == ["POST", "GET", "POST", "GET"]
    assert paths == [
        "http://core.example/search",
        "http://core.example/search/poll/sid-1",
        "http://core.example/packages",
        "http://core.example/packages/poll/pid-1",
    ]


@pytest.mark.asyncio
async def test_core_app_client_returns_logs_on_timeout():
    client = AsyncMock()
    client.request = AsyncMock(
        side_effect=[
            _Response({"sId": "sid-1"}),
            _Response({"searchStatus": "COMPLETED_SUCCESSFULLY", "searchResults": [{"hotelId": "1043546"}]}),
            _Response({"pId": "pid-1"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
            _Response({"status": "PENDING"}),
        ]
    )

    core = CoreAppClient(client=client)
    core.settings.core_app_url = "http://core.example"

    result = await core.run_search_and_packages(
        api_key="api-key-1",
        check_in="2026-09-01",
        check_out="2026-09-03",
        hotel_id="1043546",
    )

    assert result.search_s_id == "sid-1"
    assert result.package_p_id == "pid-1"
    assert result.package_status == ""
    assert result.error_message and "timed out" in result.error_message
    assert len(result.logs) == 19
    assert result.logs[-1]["step"] == "packages"
