import pytest

from app.config import get_settings
from app.db.database import init_db, reset_engine
from app.models.scenario import ScenarioRequest


@pytest.fixture(autouse=True)
def mock_hotel_mapping(monkeypatch):
    async def fake_resolve(request: ScenarioRequest) -> ScenarioRequest:
        data = request.model_dump(mode="json")
        atg = data["atg_hotel_id"]
        data["supplier_hotel_ids"] = {
            s["code"]: f"sup-{atg}-{s['code']}" for s in data["suppliers"]
        }
        return ScenarioRequest.model_validate(data)

    monkeypatch.setattr(
        "app.api.routes.scenarios.resolve_scenario_hotel_ids",
        fake_resolve,
    )


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    db_path = tmp_path / "smf-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    init_db()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client

    reset_engine()
    get_settings.cache_clear()
