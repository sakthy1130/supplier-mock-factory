from unittest.mock import AsyncMock, patch

import pytest

from app.core.orchestrator import SupplierMockScenarioOrchestrator
from app.core.scenario_engine import BuiltExpectation
from app.models.scenario import PackageSpec, ScenarioRequest, ScenarioStatus, SupplierCode, SupplierScenario


def _request(**overrides) -> ScenarioRequest:
    payload = dict(
        namespace="qa-orch-001",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "156652"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.HBS,
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]),
            ),
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]),
            ),
        ],
    )
    payload.update(overrides)
    return ScenarioRequest(**payload)


def _crawla_request() -> ScenarioRequest:
    request = _request()
    data = request.model_dump(mode="json")
    data["crawla_export"] = {"bucket": "CRAWLA_LOWER"}
    return ScenarioRequest.model_validate(data)


@pytest.mark.asyncio
async def test_create_scenario_end_to_end_with_mocks():
    built = [
        BuiltExpectation(
            supplier_code="HBS",
            log_type="Search",
            expectation={"httpRequest": {"path": "/hotel-api/1.2/hotels"}},
        ),
        BuiltExpectation(
            supplier_code="EXP",
            log_type="Search",
            expectation={"httpRequest": {"path": "/v3/properties/availability"}},
        ),
    ]

    engine = AsyncMock()
    engine.build_expectations = lambda request: built

    contract_provisioner = AsyncMock()
    contract_provisioner.create_contracts = AsyncMock(
        return_value={"HBS": "contract-hbs", "EXP": "contract-exp"}
    )

    apikey_provisioner = AsyncMock()
    apikey_provisioner.create_api_key = AsyncMock(return_value=("smf-qa-orch-001", "key-id-99"))

    orchestrator = SupplierMockScenarioOrchestrator(
        engine=engine,
        contract_provisioner=contract_provisioner,
        apikey_provisioner=apikey_provisioner,
    )
    orchestrator.settings.mock_server_url = "http://mockserver-staging.tajawal.io"

    with patch(
        "app.core.orchestrator.register_built_expectations",
        new=AsyncMock(return_value={"HBS": "148-1111111", "EXP": "7556000000001"}),
    ):
        bundle = await orchestrator.create_scenario(_request())

    assert bundle.status == ScenarioStatus.READY
    assert bundle.api_key == "smf-qa-orch-001"
    assert bundle.api_key_id == "key-id-99"
    assert bundle.contracts == {"HBS": "contract-hbs", "EXP": "contract-exp"}
    assert bundle.booking_ids == {"HBS": "148-1111111", "EXP": "7556000000001"}
    assert bundle.expectation_count == 2
    assert bundle.mock_server_base_url == "http://mockserver-staging.tajawal.io"

    contract_provisioner.create_contracts.assert_awaited_once()
    apikey_provisioner.create_api_key.assert_awaited_once()
    ak_call = apikey_provisioner.create_api_key.await_args
    assert ak_call.args[0] == {"HBS": "contract-hbs", "EXP": "contract-exp"}
    assert ak_call.args[1] == "qa-orch-001"
    # Non-SB scenario: no SB config/group injected at create time
    assert ak_call.kwargs.get("sb_config_data") is None
    assert ak_call.kwargs.get("sb_group_data") is None


@pytest.mark.asyncio
async def test_sb_scenario_splits_contracts_by_target():
    engine = AsyncMock()
    engine.build_expectations = lambda request: []

    contract_provisioner = AsyncMock()
    contract_provisioner.create_contracts = AsyncMock(
        return_value={"HBS": "c-hbs", "EXP": "c-exp", "EXT": "c-ext"}
    )

    apikey_provisioner = AsyncMock()
    apikey_provisioner.create_api_key = AsyncMock(return_value=("smf-qa-orch-001", "key-id-99"))

    sb_group_provisioner = AsyncMock()
    sb_group_provisioner.create_group = AsyncMock(return_value={"_id": "grp-1", "name": "smf-sb-x"})
    sb_group_provisioner.create_sb_config = AsyncMock(return_value={"_id": "cfg-1", "name": "smf-sb-x"})

    br_provisioner = AsyncMock()
    br_provisioner.provision = AsyncMock(return_value={"status": "SUCCESS", "errors": []})

    orchestrator = SupplierMockScenarioOrchestrator(
        engine=engine,
        contract_provisioner=contract_provisioner,
        apikey_provisioner=apikey_provisioner,
        sb_group_provisioner=sb_group_provisioner,
        br_provisioner=br_provisioner,
    )

    # HBS→apikey, EXP→sbgroup, EXT→both
    request = _request(
        sb_enabled=True,
        suppliers=[
            SupplierScenario(code=SupplierCode.HBS, packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]), assignment_target="apikey"),
            SupplierScenario(code=SupplierCode.EXP, packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]), assignment_target="sbgroup"),
            SupplierScenario(code=SupplierCode.EXT, packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]), assignment_target="both"),
        ],
    )

    with patch("app.core.orchestrator.register_built_expectations", new=AsyncMock(return_value={})):
        bundle = await orchestrator.create_scenario(request)

    assert bundle.status == ScenarioStatus.READY
    # SB group gets sbgroup + both contracts
    grp_call = sb_group_provisioner.create_group.await_args
    assert sorted(grp_call.kwargs["contract_ids"]) == sorted(["c-exp", "c-ext"])
    # apiKey gets apikey + both contracts (not the sbgroup-only one)
    ak_call = apikey_provisioner.create_api_key.await_args
    assert ak_call.args[0] == {"HBS": "c-hbs", "EXT": "c-ext"}
    # bundle.contracts keeps ALL suppliers for teardown
    assert bundle.contracts == {"HBS": "c-hbs", "EXP": "c-exp", "EXT": "c-ext"}


@pytest.mark.asyncio
async def test_create_normal_scenario_provisions_br_by_default():
    engine = AsyncMock()
    engine.build_expectations = lambda request: []

    contract_provisioner = AsyncMock()
    contract_provisioner.create_contracts = AsyncMock(return_value={"HBS": "contract-hbs"})

    apikey_provisioner = AsyncMock()
    apikey_provisioner.create_api_key = AsyncMock(return_value=("smf-qa-orch-001", "key-id-99"))

    br_provisioner = AsyncMock()
    br_provisioner.provision = AsyncMock(return_value={"enabled": True, "status": "SUCCESS", "errors": []})

    orchestrator = SupplierMockScenarioOrchestrator(
        engine=engine,
        contract_provisioner=contract_provisioner,
        apikey_provisioner=apikey_provisioner,
        br_provisioner=br_provisioner,
    )

    with patch("app.core.orchestrator.register_built_expectations", new=AsyncMock(return_value={})):
        bundle = await orchestrator.create_scenario(_request())

    assert bundle.status == ScenarioStatus.READY
    br_provisioner.provision.assert_awaited_once_with("smf-qa-orch-001", template_id=None)


@pytest.mark.asyncio
async def test_create_normal_scenario_skips_br_when_opted_out():
    engine = AsyncMock()
    engine.build_expectations = lambda request: []

    contract_provisioner = AsyncMock()
    contract_provisioner.create_contracts = AsyncMock(return_value={"HBS": "contract-hbs"})

    apikey_provisioner = AsyncMock()
    apikey_provisioner.create_api_key = AsyncMock(return_value=("smf-qa-orch-001", "key-id-99"))

    br_provisioner = AsyncMock()
    br_provisioner.provision = AsyncMock()

    orchestrator = SupplierMockScenarioOrchestrator(
        engine=engine,
        contract_provisioner=contract_provisioner,
        apikey_provisioner=apikey_provisioner,
        br_provisioner=br_provisioner,
    )

    with patch("app.core.orchestrator.register_built_expectations", new=AsyncMock(return_value={})):
        bundle = await orchestrator.create_scenario(_request(assign_to_br=False))

    assert bundle.status == ScenarioStatus.READY
    br_provisioner.provision.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_crawla_scenario_provisions_br_warning_non_blocking():
    engine = AsyncMock()
    engine.build_expectations = lambda request: []

    contract_provisioner = AsyncMock()
    contract_provisioner.create_contracts = AsyncMock(return_value={"HBS": "contract-hbs"})

    apikey_provisioner = AsyncMock()
    apikey_provisioner.create_api_key = AsyncMock(return_value=("smf-qa-orch-001", "key-id-99"))

    br_provisioner = AsyncMock()
    br_provisioner.provision = AsyncMock(
        return_value={"status": "FAILED", "warning": "BR setup failed", "errors": [{"step": "assign_static"}]}
    )

    orchestrator = SupplierMockScenarioOrchestrator(
        engine=engine,
        contract_provisioner=contract_provisioner,
        apikey_provisioner=apikey_provisioner,
        br_provisioner=br_provisioner,
    )

    with patch("app.core.orchestrator.register_built_expectations", new=AsyncMock(return_value={})):
        bundle = await orchestrator.create_scenario(_crawla_request())

    assert bundle.status == ScenarioStatus.READY
    assert bundle.error_message == "BR setup failed"
    assert bundle.br_setup and bundle.br_setup["status"] == "FAILED"
    br_provisioner.provision.assert_awaited_once_with("smf-qa-orch-001", template_id=None)


@pytest.mark.asyncio
async def test_teardown_only_cleans_br_when_metadata_exists():
    br_provisioner = AsyncMock()
    br_provisioner.cleanup = AsyncMock()

    class FakeMockServerClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def delete_by_namespace(self, namespace, *, suppliers=None):
            return None

    orchestrator = SupplierMockScenarioOrchestrator(br_provisioner=br_provisioner)

    with patch("app.core.orchestrator.MockServerClient", FakeMockServerClient):
        await orchestrator.teardown_scenario("normal-ns", api_key="smf-normal")
        await orchestrator.teardown_scenario(
            "crawla-ns",
            api_key="smf-crawla",
            br_setup={"status": "SUCCESS", "rules": {}},
        )

    br_provisioner.cleanup.assert_awaited_once_with(
        {"status": "SUCCESS", "rules": {}},
        "smf-crawla",
    )
