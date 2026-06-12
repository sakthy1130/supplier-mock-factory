from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.quickwit_indices import resolve_console_logs_index
from app.integrations.quickwit import QuickwitClient, extract_hits, hit_count
from app.services.quickwit_service import run_quickwit_search


def test_resolve_staging_index():
    base = "http://quickwit-nonprod.tajawal-prod-devops.internal/api/v1"
    assert (
        resolve_console_logs_index(base, on_date=date(2026, 6, 6))
        == "hotels-consolelogs-staging-2026_06_06"
    )


def test_resolve_prod_index():
    base = "http://quickwit-prod.tajawal-prod-devops.internal/api/v1"
    assert (
        resolve_console_logs_index(base, on_date=date(2026, 6, 6))
        == "hotels-consolelogs-prod-apps-2026_06"
    )


def test_extract_hits_from_activator_shape():
    raw = {
        "status": 200,
        "body": {"hits": [{"message": "line1"}, {"message": "line2"}], "num_hits": 2},
    }
    assert len(extract_hits(raw)) == 2
    assert hit_count(raw) == 2


@pytest.mark.asyncio
async def test_quickwit_client_search(monkeypatch):
    response = MagicMock(status_code=200)
    response.json.return_value = {"hits": [{"body": "ok"}], "num_hits": 1}
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)

    qw = QuickwitClient(client=client)
    qw.base_url = "http://quickwit.example/api/v1"
    qw.settings.quickwit_logs_api_url = qw.base_url

    result = await qw.search(
        "hotels-consolelogs-staging-2026_06_06",
        "smf-test",
        max_hits=10,
        start_timestamp=1_700_000_000,
    )
    assert result["status"] == 200
    assert extract_hits(result) == [{"body": "ok"}]
    client.post.assert_awaited_once()
    call_kwargs = client.post.await_args.kwargs
    assert call_kwargs["json"]["query"] == "smf-test"
    assert call_kwargs["headers"]["x-user-agent"] == "qa_automation"


@pytest.mark.asyncio
async def test_run_quickwit_search(monkeypatch):
    async def fake_search_last_minutes(self, index, query, minutes, *, max_hits=3000):
        return {
            "status": 200,
            "body": {"hits": [{"query": query, "index": index}], "num_hits": 1},
        }

    monkeypatch.setattr(QuickwitClient, "search_last_minutes", fake_search_last_minutes)
    monkeypatch.setattr(
        "app.services.quickwit_service.get_settings",
        lambda: type(
            "S",
            (),
            {
                "quickwit_logs_api_url": "http://quickwit-nonprod.tajawal-prod-devops.internal/api/v1",
            },
        )(),
    )

    result = await run_quickwit_search("smf-qa-1", index=None, minutes=30, max_hits=100)
    assert result.num_hits == 1
    assert result.query == "smf-qa-1"
    assert result.index == "hotels-consolelogs-staging-2026_06_06" or result.index.startswith(
        "hotels-consolelogs-staging-"
    )
