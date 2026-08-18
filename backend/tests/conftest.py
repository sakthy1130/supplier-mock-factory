import uuid

import pytest

from app.config import clear_settings_cache, get_settings
from app.db.database import init_db, ping, reset_client
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
def api_client(monkeypatch):
    """TestClient backed by a real mongod, in throwaway collections.

    Isolation is per COLLECTION, not per database: the app user is granted rights on
    a single database (`authSource=appdb`), so creating/dropping a database per test
    fails with "not authorized". A unique collection prefix gives the same isolation
    inside the database the user does own, and the collections are dropped on
    teardown — so a test run never sees or touches real scenarios and templates.

    Requires a reachable mongod; MONGO_URL comes from backend/.env* as usual.
    """
    prefix = f"test_{uuid.uuid4().hex[:12]}_"
    monkeypatch.setenv("MONGO_COLLECTION_PREFIX", prefix)
    clear_settings_cache()
    reset_client()

    settings = get_settings()
    if not settings.mongo_url:
        pytest.fail("MONGO_URL is not set — add it to backend/.env or backend/.env.shared.")
    try:
        ping()
    except RuntimeError as exc:
        pytest.fail(f"{exc}\nStart mongod (or point MONGO_URL at a reachable server) to run DB tests.")

    init_db()

    from fastapi.testclient import TestClient

    from app.main import app

    try:
        with TestClient(app) as client:
            yield client
    finally:
        from app.db.database import get_database
        from app.db.repository import collection_names

        database = get_database()
        for name in collection_names(prefix):
            database.drop_collection(name)
        reset_client()
        clear_settings_cache()
