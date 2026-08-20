import pytest

from app.config import clear_settings_cache
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
    from app.services.supplier_service import invalidate_cache

    db_path = tmp_path / "smf-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    clear_settings_cache()
    reset_engine()
    # Supplier configs are cached per (code, env) and outlive the engine, so a config read
    # against an earlier test's database — or a miss recorded before seeding — would be
    # served to this one. Drop it at both ends so each test sees only its own DB.
    invalidate_cache()
    init_db()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client

    reset_engine()
    clear_settings_cache()
    invalidate_cache()
