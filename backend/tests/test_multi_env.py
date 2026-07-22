"""Multi-env support: X-SMF-Env resolution, scenario env tagging, list filtering."""

from datetime import datetime, timezone

import pytest

from app import config as config_module
from app.config import clear_settings_cache, get_settings
from app.env_context import DEFAULT_ENV, SUPPORTED_ENVS, normalize_env
from app.models.scenario import ScenarioBundle, ScenarioStatus


def _request_payload(namespace: str) -> dict:
    return {
        "namespace": namespace,
        "check_in": "2026-09-01",
        "check_out": "2026-09-03",
        "atg_hotel_id": "1446194",
        "suppliers": [
            {
                "code": "HBS",
                "packages": {"count": 1, "room_basis": "RO", "prices": [100.0]},
            }
        ],
    }


def _ready_bundle(namespace: str) -> ScenarioBundle:
    return ScenarioBundle(
        namespace=namespace,
        status=ScenarioStatus.READY,
        api_key="smf-test-key",
        api_key_id="key-id-1",
        contracts={"HBS": "contract-1"},
        booking_ids={"HBS": "148-1111111"},
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "156652"},
        mock_server_base_url="http://mock.example",
        expectation_count=6,
        created_at=datetime.now(timezone.utc),
    )


def test_env_context_normalize_and_defaults():
    assert DEFAULT_ENV == "dev"
    assert set(SUPPORTED_ENVS) == {"dev", "stg"}
    assert normalize_env(None) == "dev"
    assert normalize_env("") == "dev"
    assert normalize_env("bogus") == "dev"
    assert normalize_env("STG") == "stg"
    assert normalize_env(" dev ") == "dev"


def test_settings_layering_is_distinct_per_env(tmp_path, monkeypatch):
    # Use throwaway env files so this test is independent of the developer's real
    # (gitignored) backend/.env.{dev,stg,shared) secrets — and of whether they exist.
    (tmp_path / ".env.shared").write_text("CRAWLA_API_KEY=shared-key\n")
    (tmp_path / ".env.dev").write_text("MOCK_SERVER_URL=http://mock-dev.example\n")
    (tmp_path / ".env.stg").write_text("MOCK_SERVER_URL=http://mock-stg.example\n")
    monkeypatch.setattr(config_module, "BACKEND_DIR", tmp_path)
    monkeypatch.setattr(config_module, "BACKEND_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("MOCK_SERVER_URL", raising=False)
    monkeypatch.delenv("CRAWLA_API_KEY", raising=False)
    clear_settings_cache()
    try:
        dev = get_settings("dev")
        stg = get_settings("stg")
        assert dev.env == "dev"
        assert stg.env == "stg"
        assert dev.mock_server_url == "http://mock-dev.example"
        assert stg.mock_server_url == "http://mock-stg.example"
        # shared values (from .env.shared) are inherited by both
        assert dev.crawla_api_key == stg.crawla_api_key == "shared-key"
    finally:
        clear_settings_cache()  # don't leak throwaway-path settings into other tests


def test_health_reports_resolved_env(api_client):
    assert api_client.get("/health").json()["env"] == "dev"
    assert api_client.get("/health", headers={"X-SMF-Env": "stg"}).json()["env"] == "stg"
    # unknown header value falls back to default, never 500s
    assert api_client.get("/health", headers={"X-SMF-Env": "prod"}).json()["env"] == "dev"


def test_api_env_endpoint(api_client):
    data = api_client.get("/api/env").json()
    assert data["default"] == "dev"
    assert set(data["available"]) == {"dev", "stg"}
    assert data["current"] == "dev"
    assert api_client.get("/api/env", headers={"X-SMF-Env": "stg"}).json()["current"] == "stg"


@pytest.mark.usefixtures("api_client")
class TestScenarioEnvTagging:
    def test_create_without_header_defaults_to_dev(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        created = api_client.post("/api/scenarios", json=_request_payload("env-default-001")).json()
        assert created["env"] == "dev"

    def test_create_with_stg_header_tags_stg(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        created = api_client.post(
            "/api/scenarios",
            json=_request_payload("env-stg-001"),
            headers={"X-SMF-Env": "stg"},
        ).json()
        assert created["env"] == "stg"

    def test_list_filters_by_active_env(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        api_client.post("/api/scenarios", json=_request_payload("env-list-dev"))
        api_client.post(
            "/api/scenarios",
            json=_request_payload("env-list-stg"),
            headers={"X-SMF-Env": "stg"},
        )

        dev_items = api_client.get("/api/scenarios").json()
        dev_namespaces = {item["namespace"] for item in dev_items}
        assert "env-list-dev" in dev_namespaces
        assert "env-list-stg" not in dev_namespaces

        stg_items = api_client.get("/api/scenarios", headers={"X-SMF-Env": "stg"}).json()
        stg_namespaces = {item["namespace"] for item in stg_items}
        assert "env-list-stg" in stg_namespaces
        assert "env-list-dev" not in stg_namespaces

        all_items = api_client.get("/api/scenarios?env=all").json()
        all_namespaces = {item["namespace"] for item in all_items}
        assert {"env-list-dev", "env-list-stg"} <= all_namespaces

    def test_teardown_all_scoped_to_active_env(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        async def fake_teardown(self, namespace, **kwargs):
            return ScenarioBundle(namespace=namespace, status=ScenarioStatus.TORN_DOWN)

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.teardown_scenario",
            fake_teardown,
        )

        async def fake_delete_all(self):
            return None

        monkeypatch.setattr(
            "app.integrations.mock_server.MockServerClient.delete_all_expectations",
            fake_delete_all,
        )

        api_client.post("/api/scenarios", json=_request_payload("env-teardown-dev"))
        api_client.post(
            "/api/scenarios",
            json=_request_payload("env-teardown-stg"),
            headers={"X-SMF-Env": "stg"},
        )

        # Clear all in the (default) dev context — must not queue the stg scenario.
        result = api_client.delete("/api/scenarios/all").json()
        assert result["queued"] == 1

        remaining_stg = api_client.get("/api/scenarios", headers={"X-SMF-Env": "stg"}).json()
        assert any(item["namespace"] == "env-teardown-stg" for item in remaining_stg)
