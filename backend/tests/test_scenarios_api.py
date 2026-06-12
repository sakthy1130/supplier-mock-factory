from datetime import datetime, timezone
import pytest

from app.models.scenario import ScenarioBundle, ScenarioStatus


def _request_payload(namespace: str = "api-test-001") -> dict:
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


def _crawla_request_payload(namespace: str = "crawla-api-test-001") -> dict:
    return {
        "namespace": namespace,
        "check_in": "2026-09-01",
        "check_out": "2026-09-03",
        "atg_hotel_id": "1043546",
        "bucket": "CRAWLA_LOWER",
        "search": {
            "crawla_total": 6795.1,
            "exp_mode": "INCLUDE_HOTEL",
            "exp_price": 7500.0,
            "hbs_price": 8000.0,
        },
        "packages": {
            "crawla_total": 6795.1,
            "crawla_room_id": "690304e7-6bb9-4525-aaa9-3ce253c11842",
            "crawla_room_name": "Deluxe Room",
            "room_basis": "RO",
            "meal": "RO",
            "refundability": "NO",
            "exp_mode": "INCLUDE_HOTEL",
            "exp_price": 7500.0,
            "hbs_price": 8000.0,
        },
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


@pytest.mark.usefixtures("api_client")
class TestScenariosApi:
    def test_create_returns_202_pending_then_ready(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )

        response = api_client.post("/api/scenarios", json=_request_payload())
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "PENDING"
        scenario_id = data["id"]

        detail = api_client.get(f"/api/scenarios/{scenario_id}").json()
        assert detail["status"] == "READY"
        assert detail["api_key"] == "smf-test-key"
        assert detail["booking_ids"] == {"HBS": "148-1111111"}

    def test_create_duplicate_namespace_409(self, api_client):
        api_client.post("/api/scenarios", json=_request_payload("dup-ns"))
        response = api_client.post("/api/scenarios", json=_request_payload("dup-ns"))
        assert response.status_code == 409

    def test_list_scenarios(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        api_client.post("/api/scenarios", json=_request_payload("list-test-001"))
        items = api_client.get("/api/scenarios").json()
        assert len(items) >= 1
        assert items[0]["namespace"] == "list-test-001"
        assert items[0]["suppliers"] == ["HBS"]

    def test_get_scenario_not_found(self, api_client):
        assert api_client.get("/api/scenarios/missing-id").status_code == 404

    def test_refresh_booking_ids(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        async def fake_refresh(self, request):
            bundle = _ready_bundle(request.namespace)
            bundle.booking_ids = {"HBS": "148-9999999"}
            return bundle

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.refresh_booking_ids",
            fake_refresh,
        )

        created = api_client.post("/api/scenarios", json=_request_payload("refresh-test")).json()
        scenario_id = created["id"]
        api_client.get(f"/api/scenarios/{scenario_id}")

        response = api_client.post(f"/api/scenarios/{scenario_id}/refresh-booking-ids")
        assert response.status_code == 202

        detail = api_client.get(f"/api/scenarios/{scenario_id}").json()
        assert detail["booking_ids"] == {"HBS": "148-9999999"}

    def test_teardown(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        async def fake_teardown(self, namespace, **kwargs):
            return ScenarioBundle(
                namespace=namespace,
                status=ScenarioStatus.TORN_DOWN,
                check_in="2026-09-01",
                check_out="2026-09-03",
                atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "156652"},
            )

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.teardown_scenario",
            fake_teardown,
        )

        created = api_client.post("/api/scenarios", json=_request_payload("teardown-test")).json()
        scenario_id = created["id"]
        api_client.get(f"/api/scenarios/{scenario_id}")

        response = api_client.delete(f"/api/scenarios/{scenario_id}")
        assert response.status_code == 202

        assert api_client.get(f"/api/scenarios/{scenario_id}").status_code == 404

    def test_teardown_all(self, api_client, monkeypatch):
        async def fake_create(self, request):
            return _ready_bundle(request.namespace)

        async def fake_teardown(self, namespace, **kwargs):
            return ScenarioBundle(
                namespace=namespace,
                status=ScenarioStatus.TORN_DOWN,
                check_in="2026-09-01",
                check_out="2026-09-03",
                atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "156652"},
            )

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.teardown_scenario",
            fake_teardown,
        )
        async def fake_delete_all_expectations(self):
            return None

        monkeypatch.setattr(
            "app.services.scenario_service.MockServerClient.delete_all_expectations",
            fake_delete_all_expectations,
        )

        api_client.post("/api/scenarios", json=_request_payload("clear-all-1"))
        api_client.post("/api/scenarios", json=_request_payload("clear-all-2"))

        response = api_client.delete("/api/scenarios/all")
        assert response.status_code == 202
        data = response.json()
        assert data["queued"] == 2
        assert len(data["scenario_ids"]) == 2

        for scenario_id in data["scenario_ids"]:
            assert api_client.get(f"/api/scenarios/{scenario_id}").status_code == 404

    def test_crawla_run_search_and_packages(self, api_client, monkeypatch):
        async def fake_resolve(request):
            data = request.model_dump(mode="json")
            data["supplier_hotel_ids"] = {"HBS": "156652", "EXP": "50878533"}
            return type(request).model_validate(data)

        async def fake_create(self, request):
            bundle = _ready_bundle(request.namespace)
            bundle.crawla_export = request.crawla_export
            return bundle

        async def fake_run(self, api_key, check_in, check_out, hotel_id):
            assert api_key == "smf-test-key"
            assert check_in == "2026-09-01"
            assert check_out == "2026-09-03"
            assert hotel_id == "1043546"
            from app.models.crawla import CrawlaRunScenarioResponse

            return CrawlaRunScenarioResponse(
                scenario_id="",
                search_s_id="019eb293-78d9-7995-9c6e-90c55a52741d",
                search_status="COMPLETED_SUCCESSFULLY",
                search_hotel_id="1043546",
                package_p_id="413176bf-4ccf-4f36-99cb-7a9f5c8bafee",
                package_status="COMPLETED_SUCCESSFULLY",
            )

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        monkeypatch.setattr("app.api.routes.crawla.resolve_scenario_hotel_ids", fake_resolve)
        monkeypatch.setattr(
            "app.api.routes.crawla.CoreAppClient.run_search_and_packages",
            fake_run,
        )

        created = api_client.post("/api/crawla/scenarios", json=_crawla_request_payload()).json()
        scenario_id = created["id"]
        detail = api_client.get(f"/api/scenarios/{scenario_id}").json()
        assert detail["status"] == "READY"
        assert detail["api_key"] == "smf-test-key"

        response = api_client.post(f"/api/crawla/scenarios/{scenario_id}/run")
        assert response.status_code == 200
        data = response.json()
        assert data["scenario_id"] == scenario_id
        assert data["search_s_id"] == "019eb293-78d9-7995-9c6e-90c55a52741d"
        assert data["search_status"] == "COMPLETED_SUCCESSFULLY"
        assert data["package_p_id"] == "413176bf-4ccf-4f36-99cb-7a9f5c8bafee"
        assert data["package_status"] == "COMPLETED_SUCCESSFULLY"

    def test_crawla_run_returns_logs_on_core_timeout(self, api_client, monkeypatch):
        async def fake_resolve(request):
            data = request.model_dump(mode="json")
            data["supplier_hotel_ids"] = {"HBS": "156652", "EXP": "50878533"}
            return type(request).model_validate(data)

        async def fake_create(self, request):
            bundle = _ready_bundle(request.namespace)
            bundle.crawla_export = request.crawla_export
            return bundle

        from app.models.crawla import CrawlaRunScenarioResponse

        async def fake_run(self, api_key, check_in, check_out, hotel_id):
            return CrawlaRunScenarioResponse(
                scenario_id="",
                search_s_id="019eb293-78d9-7995-9c6e-90c55a52741d",
                search_status="COMPLETED_SUCCESSFULLY",
                search_hotel_id="1043546",
                package_p_id="413176bf-4ccf-4f36-99cb-7a9f5c8bafee",
                package_status="",
                error_message="Core polling timed out at /packages/poll/413176bf-4ccf-4f36-99cb-7a9f5c8bafee after 16 attempts; last='PENDING'",
                logs=[
                    {
                        "step": "search",
                        "method": "POST",
                        "path": "/search",
                        "attempt": "1",
                        "status": "COMPLETED_SUCCESSFULLY",
                        "http_status": "200",
                    }
                ],
            )

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        monkeypatch.setattr("app.api.routes.crawla.resolve_scenario_hotel_ids", fake_resolve)
        monkeypatch.setattr(
            "app.api.routes.crawla.CoreAppClient.run_search_and_packages",
            fake_run,
        )

        created = api_client.post("/api/crawla/scenarios", json=_crawla_request_payload()).json()
        scenario_id = created["id"]

        response = api_client.post(f"/api/crawla/scenarios/{scenario_id}/run")
        assert response.status_code == 200
        data = response.json()
        assert data["scenario_id"] == scenario_id
        assert data["error_message"]
        assert data["logs"]

    def test_crawla_create_maps_package_count_and_price_mode(self, api_client, monkeypatch):
        captured = {}

        async def fake_resolve(request):
            data = request.model_dump(mode="json")
            data["supplier_hotel_ids"] = {"HBS": "156652", "EXP": "50878533"}
            return type(request).model_validate(data)

        async def fake_create(self, request):
            captured["count"] = request.suppliers[0].packages.count
            captured["prices"] = request.suppliers[0].packages.prices
            return _ready_bundle(request.namespace)

        payload = _crawla_request_payload("crawla-count-test")
        payload["packages"]["package_count"] = 3
        payload["packages"]["package_price_mode"] = "INCREASE"
        payload["packages"]["package_price_step"] = 25.0
        payload["packages"]["hbs_price"] = 8000.0
        payload["packages"]["exp_price"] = 7500.0

        monkeypatch.setattr(
            "app.services.scenario_service.SupplierMockScenarioOrchestrator.create_scenario",
            fake_create,
        )
        monkeypatch.setattr("app.api.routes.crawla.resolve_scenario_hotel_ids", fake_resolve)

        response = api_client.post("/api/crawla/scenarios", json=payload)
        assert response.status_code == 202
        assert captured["count"] == 3
        assert captured["prices"] == [8000.0, 8025.0, 8050.0]
