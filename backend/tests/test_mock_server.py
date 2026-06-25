from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.core.namespace import ALL_SCENARIO_LOG_TYPES, SCENARIO_SUPPLIER_CODES
from app.integrations.mock_server import MockServerClient, MockServerError


@pytest.mark.asyncio
async def test_register_expectation_success():
    response = MagicMock(status_code=201, text="[]")
    client = AsyncMock()
    client.put = AsyncMock(return_value=response)

    mock_server = MockServerClient(client=client)
    await mock_server.register_expectation({"httpRequest": {"path": "/test"}, "priority": 1000})

    client.put.assert_awaited_once()
    assert client.put.await_args.args[0].endswith("/mockserver/expectation")


@pytest.mark.asyncio
async def test_register_expectation_failure_raises():
    response = MagicMock(status_code=500, text="error")
    client = AsyncMock()
    client.put = AsyncMock(return_value=response)

    mock_server = MockServerClient(client=client)
    with pytest.raises(MockServerError):
        await mock_server.register_expectation({"priority": 1000})


@pytest.mark.asyncio
async def test_delete_by_namespace_scoped_to_suppliers():
    response = MagicMock(status_code=200, text="{}")
    client = AsyncMock()
    client.put = AsyncMock(return_value=response)

    mock_server = MockServerClient(client=client)
    await mock_server.delete_by_namespace("qa-test-ns", suppliers=["HBS", "EXP"])

    assert client.put.await_count == 14
    ids = [call.kwargs["json"]["id"] for call in client.put.await_args_list]
    assert all("-rhk-" not in expectation_id for expectation_id in ids)


@pytest.mark.asyncio
async def test_delete_by_namespace_clears_by_expectation_id():
    response = MagicMock(status_code=200, text="{}")
    client = AsyncMock()
    client.put = AsyncMock(return_value=response)

    mock_server = MockServerClient(client=client)
    await mock_server.delete_by_namespace("qa-test-ns")

    assert client.put.await_count == len(SCENARIO_SUPPLIER_CODES) * len(ALL_SCENARIO_LOG_TYPES)
    first_kwargs = client.put.await_args_list[0].kwargs
    assert first_kwargs["params"] == {"type": "expectations"}
    assert first_kwargs["json"]["id"] == "smf-qa-test-ns-hbs-search"


@pytest.mark.asyncio
async def test_delete_all_expectations_clears_everything():
    response = MagicMock(status_code=200, text="{}")
    client = AsyncMock()
    client.put = AsyncMock(return_value=response)

    mock_server = MockServerClient(client=client)
    await mock_server.delete_all_expectations()

    client.put.assert_awaited_once()
    assert client.put.await_args.kwargs["json"] == {}
