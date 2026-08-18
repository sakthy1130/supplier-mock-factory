"""Provisioning depth: how far scenario creation goes past mocks + contracts.

`full` is the historical path (new apiKey, apiKey -> BR). The two contract depths stop
earlier and may instead attach the contracts to an apiKey the caller already owns —
which teardown must never delete.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.apikey_provisioner import _writable_api_key_body
from app.core.orchestrator import SupplierMockScenarioOrchestrator
from app.models.scenario import (
    PackageSpec,
    ProvisioningDepth,
    ScenarioRequest,
    SupplierCode,
    SupplierScenario,
)


def _request(**overrides) -> ScenarioRequest:
    payload = {
        "namespace": "qa-depth-001",
        "check_in": "2026-09-01",
        "check_out": "2026-09-03",
        "atg_hotel_id": "1446194",
        "suppliers": [
            SupplierScenario(
                code=SupplierCode.HBS,
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0], refundable=[True]),
            )
        ],
    }
    payload.update(overrides)
    return ScenarioRequest(**payload)


def _orchestrator(contracts: dict[str, str]) -> tuple[SupplierMockScenarioOrchestrator, dict]:
    """Orchestrator with every external provisioner stubbed, plus the stubs to assert on."""
    engine = MagicMock()
    engine.build_expectations = MagicMock(return_value=[])

    contract_provisioner = MagicMock()
    contract_provisioner.create_contracts = AsyncMock(return_value=contracts)
    # Only the contract_br depth reads autoIds back.
    contract_provisioner.fetch_contract_auto_ids = AsyncMock(
        return_value={key: f"1010{i}" for i, key in enumerate(contracts, start=3)}
    )

    apikey = MagicMock()
    apikey.create_api_key = AsyncMock(return_value=("smf-qa-depth-001", "key-mongo-1"))
    apikey.attach_contracts = AsyncMock(return_value="existing-key-mongo-1")
    apikey.detach_contracts = AsyncMock()

    br = MagicMock()
    br.provision = AsyncMock(return_value={"status": "SUCCESS", "errors": []})
    br.provision_for_contracts = AsyncMock(return_value={"status": "SUCCESS", "errors": []})
    br.cleanup = AsyncMock(return_value={"status": "SUCCESS", "errors": []})

    orchestrator = SupplierMockScenarioOrchestrator(
        engine=engine,
        contract_provisioner=contract_provisioner,
        apikey_provisioner=apikey,
        br_provisioner=br,
        sb_group_provisioner=MagicMock(),
    )
    return orchestrator, {"apikey": apikey, "br": br, "contracts": contract_provisioner}


# --- validation --------------------------------------------------------------


def test_full_is_the_default():
    assert _request().provisioning_depth is ProvisioningDepth.full


def test_smart_booking_requires_full():
    """Silently dropping sb_enabled would read as "SmartBooking is broken" rather than
    "that depth has no apiKey to put it on"."""
    with pytest.raises(ValidationError, match="requires provisioning_depth='full'"):
        _request(provisioning_depth="contract_only", sb_enabled=True)


def test_existing_api_key_is_rejected_for_full():
    with pytest.raises(ValidationError, match="only applies to provisioning_depth"):
        _request(existing_api_key="tj-htl-test-bookable")


def test_contract_depths_accept_an_existing_api_key():
    request = _request(provisioning_depth="contract_br", existing_api_key="tj-htl-test-bookable")
    assert request.existing_api_key == "tj-htl-test-bookable"


# --- orchestration -----------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_only_creates_no_api_key_and_no_br(monkeypatch):
    monkeypatch.setattr("app.core.orchestrator.register_built_expectations", AsyncMock(return_value={}))
    orchestrator, stubs = _orchestrator({"HBS": "contract-1"})

    bundle = await orchestrator.create_scenario(_request(provisioning_depth="contract_only"))

    assert bundle.contracts == {"HBS": "contract-1"}
    assert bundle.api_key is None and bundle.api_key_id is None
    assert bundle.api_key_is_external is False
    stubs["apikey"].create_api_key.assert_not_awaited()
    stubs["apikey"].attach_contracts.assert_not_awaited()
    stubs["br"].provision.assert_not_awaited()
    stubs["br"].provision_for_contracts.assert_not_awaited()


@pytest.mark.asyncio
async def test_contract_br_assigns_contracts_not_the_api_key(monkeypatch):
    """Even with an existing apiKey supplied, the depth decides: contract conditions
    only. The apiKey is just somewhere to hang the contract."""
    monkeypatch.setattr("app.core.orchestrator.register_built_expectations", AsyncMock(return_value={}))
    orchestrator, stubs = _orchestrator({"HBS": "contract-1"})

    bundle = await orchestrator.create_scenario(
        _request(provisioning_depth="contract_br", existing_api_key="tj-htl-test-bookable")
    )

    stubs["br"].provision_for_contracts.assert_awaited_once()
    stubs["br"].provision.assert_not_awaited()
    refs = stubs["br"].provision_for_contracts.await_args.args[0]
    # autoId rides along because the "contractId IN" condition matches on it.
    assert refs == [
        {
            "instance_key": "HBS",
            "uid": "smf-qa-depth-001-hbs",
            "id": "contract-1",
            "autoId": "10103",
        }
    ]

    stubs["apikey"].create_api_key.assert_not_awaited()
    stubs["apikey"].attach_contracts.assert_awaited_once_with(
        "tj-htl-test-bookable", ["contract-1"], prov_log=bundle.provisioning_log
    )
    assert bundle.api_key == "tj-htl-test-bookable"
    assert bundle.api_key_is_external is True


@pytest.mark.asyncio
async def test_full_is_unchanged(monkeypatch):
    monkeypatch.setattr("app.core.orchestrator.register_built_expectations", AsyncMock(return_value={}))
    orchestrator, stubs = _orchestrator({"HBS": "contract-1"})

    bundle = await orchestrator.create_scenario(_request())

    stubs["apikey"].create_api_key.assert_awaited_once()
    stubs["br"].provision.assert_awaited_once()
    stubs["br"].provision_for_contracts.assert_not_awaited()
    assert bundle.api_key == "smf-qa-depth-001"
    assert bundle.api_key_is_external is False


# --- teardown ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_teardown_never_deletes_an_external_api_key(monkeypatch):
    """The whole point of api_key_is_external: a shared apiKey must survive cleanup,
    with our contracts detached from it BEFORE they are deleted."""
    orchestrator, stubs = _orchestrator({})
    backoffice = MagicMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=False)
    backoffice.delete_contract = AsyncMock()
    backoffice.delete_api_key = AsyncMock()
    monkeypatch.setattr("app.core.orchestrator.BackofficeClient", lambda: backoffice)

    mock_server = MagicMock()
    mock_server.__aenter__ = AsyncMock(return_value=mock_server)
    mock_server.__aexit__ = AsyncMock(return_value=False)
    mock_server.delete_by_namespace = AsyncMock()
    monkeypatch.setattr("app.core.orchestrator.MockServerClient", lambda: mock_server)

    await orchestrator.teardown_scenario(
        "qa-depth-001",
        api_key="tj-htl-test-bookable",
        api_key_id="existing-key-mongo-1",
        contracts={"HBS": "contract-1"},
        api_key_is_external=True,
    )

    backoffice.delete_api_key.assert_not_awaited()
    backoffice.delete_contract.assert_awaited_once_with("contract-1")
    stubs["apikey"].detach_contracts.assert_awaited_once_with(
        "tj-htl-test-bookable", ["contract-1"]
    )


@pytest.mark.asyncio
async def test_teardown_still_deletes_an_smf_created_api_key(monkeypatch):
    orchestrator, stubs = _orchestrator({})
    backoffice = MagicMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=False)
    backoffice.delete_contract = AsyncMock()
    backoffice.delete_api_key = AsyncMock()
    monkeypatch.setattr("app.core.orchestrator.BackofficeClient", lambda: backoffice)

    mock_server = MagicMock()
    mock_server.__aenter__ = AsyncMock(return_value=mock_server)
    mock_server.__aexit__ = AsyncMock(return_value=False)
    mock_server.delete_by_namespace = AsyncMock()
    monkeypatch.setattr("app.core.orchestrator.MockServerClient", lambda: mock_server)

    await orchestrator.teardown_scenario(
        "qa-depth-001",
        api_key="smf-qa-depth-001",
        api_key_id="key-mongo-1",
        contracts={"HBS": "contract-1"},
    )

    backoffice.delete_api_key.assert_awaited_once_with("key-mongo-1")
    stubs["apikey"].detach_contracts.assert_not_awaited()


# --- the safe-PUT recipe -----------------------------------------------------


def test_writable_api_key_body_strips_read_only_fields_and_flattens_contracts():
    """Echoing the GET config back to PUT corrupts the record (portal GET then 500s).
    The body must lose the read-only/expanded fields and carry contracts as ids."""
    config = {
        "_id": "key-1",
        "uid": "tj-htl-test-bookable",
        "created_at": 1,
        "update_at": 2,
        "createdBy": "44",
        "updatedBy": "41",
        "userDetail": {"userId": 44},
        "nodeDetail": {"_id": "node-1"},
        "contracts": [{"_id": "contract-a", "code": "HBS"}, {"_id": "contract-b"}],
        "opt": {"smartBooking": {"isEnabled": True}},
    }

    body, current = _writable_api_key_body(config)

    assert current == ["contract-a", "contract-b"]
    assert body["contracts"] == ["contract-a", "contract-b"]
    for dropped in ("_id", "created_at", "update_at", "createdBy", "updatedBy", "userDetail", "nodeDetail"):
        assert dropped not in body, dropped
    # Everything else survives untouched — this is an update, not a rewrite.
    assert body["uid"] == "tj-htl-test-bookable"
    assert body["opt"] == {"smartBooking": {"isEnabled": True}}
    # The source config must not be mutated.
    assert config["contracts"][0] == {"_id": "contract-a", "code": "HBS"}


# --- the BR contract condition ------------------------------------------------


def _br_provisioner(env: str):
    """Provisioner whose client records the bodies it would POST."""
    client = MagicMock()
    client.settings = MagicMock(env=env)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.create_condition_raw = AsyncMock(return_value={"id": "cond-1"})
    client.delete_condition = AsyncMock()
    client.refresh = AsyncMock()
    from app.integrations.business_rules import CrawlaBusinessRulesProvisioner

    return CrawlaBusinessRulesProvisioner(client=client), client


_CONTRACT_REFS = [
    {"instance_key": "HBS", "uid": "smf-ns-hbs", "id": "mongo-1", "autoId": "10103"},
    {"instance_key": "EXP", "uid": "smf-ns-exp", "id": "mongo-2", "autoId": "10106"},
]


@pytest.mark.asyncio
async def test_contract_condition_joins_auto_ids_into_one_in_list():
    """The real condition is "contractId IN <list>" — every contract belongs in ONE
    condition, keyed on the short numeric autoId, not one condition per contract."""
    provisioner, client = _br_provisioner("dev")

    setup = await provisioner.provision_for_contracts(_CONTRACT_REFS)

    assert setup["status"] == "SUCCESS"
    assert client.create_condition_raw.await_count == 1
    body = client.create_condition_raw.await_args.args[0]
    assert body["inputValue"] == "10103,10106"
    assert body["inputDetailId"] == 30
    assert body["ruleId"] == "3"
    # The rest of the configured body is passed through untouched.
    assert body["parentRuleValueMapping"] == {"id": 5, "description": "apikey IN"}
    assert setup["contract_condition_ids"] == ["cond-1"]


@pytest.mark.asyncio
async def test_unconfigured_env_reports_not_configured_rather_than_success():
    """stg has no conditions yet. The mocks and contract are still real, so the step
    must say so instead of claiming BR success it never achieved."""
    provisioner, client = _br_provisioner("stg")

    setup = await provisioner.provision_for_contracts(_CONTRACT_REFS)

    assert setup["status"] == "NOT_CONFIGURED"
    assert "br_contract_conditions.json" in setup["warning"]
    client.create_condition_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_auto_id_fails_loudly_instead_of_sending_a_wrong_value():
    provisioner, client = _br_provisioner("dev")

    setup = await provisioner.provision_for_contracts(
        [{"instance_key": "HBS", "uid": "smf-ns-hbs", "id": "mongo-1"}]
    )

    assert setup["status"] == "FAILED"
    client.create_condition_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_contract_conditions_are_deleted_on_cleanup():
    provisioner, client = _br_provisioner("dev")

    result = await provisioner.cleanup(
        {"contract_condition_ids": ["cond-1", "cond-2"], "mode": "contract"}, None
    )

    assert result["status"] == "SUCCESS"
    assert [c.args[0] for c in client.delete_condition.await_args_list] == ["cond-1", "cond-2"]


@pytest.mark.asyncio
async def test_auto_ids_are_read_back_from_backoffice():
    """create_contract only returns the mongo _id, so the autoId the BR condition needs
    has to be read back per contract."""
    from app.core.contract_provisioner import ContractProvisioner

    backoffice = MagicMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=False)
    backoffice.get_contract = AsyncMock(
        side_effect=[{"_id": "mongo-1", "autoId": 10103}, {"_id": "mongo-2", "autoId": 10106}]
    )

    auto_ids = await ContractProvisioner(backoffice=backoffice).fetch_contract_auto_ids(
        {"HBS": "mongo-1", "EXP": "mongo-2"}
    )

    assert auto_ids == {"HBS": "10103", "EXP": "10106"}
