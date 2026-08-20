from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import scenario_service


@pytest.mark.asyncio
async def test_run_teardown_all_clears_mockserver_after_record_teardown(monkeypatch):
    records = [SimpleNamespace(id="scenario-1", namespace="qa-ns-1", env="stg")]
    teardown_mock = AsyncMock()
    delete_all_mock = AsyncMock()

    class FakeMockServerClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def delete_all_expectations(self):
            await delete_all_mock()

    monkeypatch.setattr(scenario_service, "list_tearable_records", lambda _db, env=None: records)
    monkeypatch.setattr(scenario_service, "_teardown_record", teardown_mock)
    monkeypatch.setattr(scenario_service, "MockServerClient", FakeMockServerClient)

    deleted: list[object] = []
    store = SimpleNamespace(scenarios=SimpleNamespace(delete=deleted.append))
    monkeypatch.setattr(scenario_service, "get_store_standalone", lambda: store)

    await scenario_service.run_teardown_all()

    assert teardown_mock.await_count == 1
    assert delete_all_mock.await_count == 1
    # The record is removed from the store even though teardown was stubbed out.
    assert deleted == records
