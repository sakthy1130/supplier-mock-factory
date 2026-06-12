from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import scenario_service


@pytest.mark.asyncio
async def test_run_teardown_all_clears_mockserver_after_record_teardown(monkeypatch):
    records = [SimpleNamespace(id="scenario-1", namespace="qa-ns-1")]
    teardown_mock = AsyncMock()
    delete_all_mock = AsyncMock()

    class FakeMockServerClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def delete_all_expectations(self):
            await delete_all_mock()

    monkeypatch.setattr(scenario_service, "list_tearable_records", lambda _db: records)
    monkeypatch.setattr(scenario_service, "_teardown_record", teardown_mock)
    monkeypatch.setattr(scenario_service, "MockServerClient", FakeMockServerClient)

    session = SimpleNamespace(close=lambda: None, delete=lambda _record: None, commit=lambda: None)
    monkeypatch.setattr(scenario_service, "get_session_factory_standalone", lambda: lambda: session)

    await scenario_service.run_teardown_all()

    assert teardown_mock.await_count == 1
    assert delete_all_mock.await_count == 1
