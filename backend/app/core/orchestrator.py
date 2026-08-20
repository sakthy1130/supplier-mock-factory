"""Main pipeline: mocks → contracts → SB group → apiKey → SB assign+cache → BR → READY."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.core.apikey_provisioner import ApiKeyProvisioner
from app.core.contract_provisioner import ContractProvisioner
from app.core.mock_registration import refresh_booking_flow_expectations, register_built_expectations
from app.core.mock_urls import extract_paths_from_built
from app.core.sb_group_provisioner import SBGroupProvisioner
from app.core.scenario_engine import ScenarioEngine
from app.integrations.business_rules import CrawlaBusinessRulesProvisioner
from app.integrations.backoffice import BackofficeClient, BackofficeError
from app.integrations.mock_server import MockServerClient
from app.models.scenario import (
    ProvisioningDepth,
    ScenarioBundle,
    ScenarioRequest,
    ScenarioStatus,
)

logger = logging.getLogger(__name__)


def _contract_refs(
    request: ScenarioRequest,
    contracts: dict[str, str],
    auto_ids: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Per-contract identity for the BR contract conditions.

    Which field the condition keys on is config-driven
    (field-maps/br_contract_conditions.json), so pass everything we know: the
    deterministic uid, the created mongo id, and the short numeric autoId that the
    real "contractId IN" condition matches on.
    """
    from app.core.contract_provisioner import contract_uid

    auto_ids = auto_ids or {}
    refs = []
    for instance_key, contract_id in contracts.items():
        ref = {
            "instance_key": instance_key,
            "uid": contract_uid(request.namespace, instance_key),
            "id": contract_id,
        }
        if instance_key in auto_ids:
            ref["autoId"] = auto_ids[instance_key]
        refs.append(ref)
    return refs


class SupplierMockScenarioOrchestrator:
    """Coordinates scenario creation end-to-end."""

    def __init__(
        self,
        engine: ScenarioEngine | None = None,
        contract_provisioner: ContractProvisioner | None = None,
        apikey_provisioner: ApiKeyProvisioner | None = None,
        br_provisioner: CrawlaBusinessRulesProvisioner | None = None,
        sb_group_provisioner: SBGroupProvisioner | None = None,
    ) -> None:
        self.engine = engine or ScenarioEngine()
        self.contract_provisioner = contract_provisioner or ContractProvisioner()
        self.apikey_provisioner = apikey_provisioner or ApiKeyProvisioner()
        self.br_provisioner = br_provisioner or CrawlaBusinessRulesProvisioner()
        self.sb_group_provisioner = sb_group_provisioner or SBGroupProvisioner()
        self.settings = get_settings()

    async def create_scenario(self, request: ScenarioRequest) -> ScenarioBundle:
        bundle = ScenarioBundle(
            namespace=request.namespace,
            check_in=request.check_in,
            check_out=request.check_out,
            atg_hotel_id=request.atg_hotel_id,
            supplier_hotel_ids=request.supplier_hotel_ids,
            status=ScenarioStatus.BUILDING_MOCKS,
            created_at=datetime.now(timezone.utc),
        )

        plog = bundle.provisioning_log  # shorthand — same list object

        built = self.engine.build_expectations(request)
        bundle.expectation_count = len(built)
        plog.append(f"[mocks] Built {len(built)} expectations")

        bundle.status = ScenarioStatus.REGISTERING
        bundle.booking_ids = await register_built_expectations(built)
        plog.append(f"[mocks] Registered {len(bundle.booking_ids)} booking IDs")

        mock_paths = extract_paths_from_built(built)
        mock_base = self.settings.mock_server_url

        bundle.status = ScenarioStatus.CREATING_CONTRACTS
        bundle.contracts = await self.contract_provisioner.create_contracts(
            request,
            mock_paths,
            mock_base,
        )
        plog.append(f"[contracts] Created: { {k: v for k, v in bundle.contracts.items()} }")

        # Per-supplier routing: with SB on, the apiKey and SB group each get only
        # the contracts of suppliers targeted to them (default apikey). With SB
        # off, apikey_contracts is every supplier (unchanged behavior).
        apikey_contracts = {
            code: cid
            for code, cid in bundle.contracts.items()
            if code in request.apikey_contract_codes()
        }
        sbgroup_contract_ids = [
            bundle.contracts[code]
            for code in request.sbgroup_contract_codes()
            if code in bundle.contracts
        ]

        # Step 3a: Create SB group BEFORE SB configuration and apiKey
        sb_config_data: dict | None = None
        sb_group_data: dict | None = None
        if request.sb_config is not None:
            node_id = self.settings.tenant_id
            logger.info("Creating SB group for namespace=%s", request.namespace)
            sb_group_data = await self.sb_group_provisioner.create_group(
                namespace=request.namespace,
                contract_ids=sbgroup_contract_ids,
            )
            bundle.sb_group_id = sb_group_data["_id"]
            bundle.sb_group_name = sb_group_data["name"]
            plog.append(
                f"[sb_group] POST /api/dynamic-forms/smart_booking_group → "
                f"_id={sb_group_data['_id']} name={sb_group_data['name']} "
                f"contracts={sbgroup_contract_ids}"
            )
            logger.info("SB group created: _id=%s", sb_group_data["_id"])

        # Step 3b: Create SB configuration BEFORE apiKey
        if request.sb_config is not None:
            logger.info("Creating SB configuration for namespace=%s", request.namespace)
            sb_config_data = await self.sb_group_provisioner.create_sb_config(
                sb_config=request.sb_config,
                namespace=request.namespace,
            )
            bundle.sb_config_id = sb_config_data["_id"]
            bundle.sb_config_name = sb_config_data["name"]
            plog.append(
                f"[sb_config] POST /api/dynamic-forms/smart_booking → "
                f"_id={sb_config_data['_id']} name={sb_config_data['name']}"
            )
            logger.info("SB config created: _id=%s", sb_config_data["_id"])

        # Step 4: the apiKey — created fresh for the `full` depth, or (for the
        # contract-only depths) an EXISTING one the caller named, which only receives
        # the contracts. When neither applies the scenario stops at the contracts.
        api_key: str | None = None
        api_key_id: str | None = None
        if request.provisioning_depth is ProvisioningDepth.full:
            bundle.status = ScenarioStatus.CREATING_API_KEY
            api_key, api_key_id = await self.apikey_provisioner.create_api_key(
                apikey_contracts,
                request.namespace,
                sb_config_data=sb_config_data,
                sb_group_data=sb_group_data,
                sb_enabled=(
                    request.sb_config.enable_profitable_sb
                    if request.sb_config is not None
                    else True
                ),
                prov_log=plog,
            )
        elif request.existing_api_key:
            bundle.status = ScenarioStatus.CREATING_API_KEY
            api_key = request.existing_api_key
            api_key_id = await self.apikey_provisioner.attach_contracts(
                api_key,
                list(apikey_contracts.values()),
                prov_log=plog,
            )
            # Teardown reads this to detach instead of deleting — see teardown_scenario.
            bundle.api_key_is_external = True
        else:
            plog.append(
                f"[apiKey] skipped (provisioning_depth={request.provisioning_depth.value}, "
                "no existing_api_key given)"
            )
        bundle.api_key = api_key
        bundle.api_key_id = api_key_id

        # Step 5: SB config + group are now injected into opt.smartBooking at apiKey
        # CREATE time (see ApiKeyProvisioner.create_api_key). We deliberately do NOT
        # call assign_to_api_key here: that path does a get_api_key_config + PUT, and
        # PUTting the read-config shape back corrupts the record (portal GET → 500).
        if request.sb_config is not None and sb_config_data is not None and sb_group_data is not None:
            logger.info(
                "SB config+group injected at create: api_key=%s sb_config_id=%s sb_group_id=%s",
                api_key, sb_config_data["_id"], sb_group_data["_id"],
            )
            plog.append(
                f"[sb_assign] injected at create → config={sb_config_data['_id']} "
                f"group={sb_group_data['_id']} (no post-create PUT)"
            )

        # Step 6: BR provisioning. `full` assigns the apiKey (for crawla_export, all SB
        # scenarios, and plain scenarios that opted in via assign_to_br). contract_br
        # keys its CONDITIONS on the contracts, and additionally assigns an existing
        # apiKey to the two markup rules when the caller named one — the conditions
        # still have to be evaluated under some apiKey.
        br_setup: dict | None = None
        if request.provisioning_depth is ProvisioningDepth.contract_br:
            logger.info("Provisioning Business Rules for contracts=%s", list(bundle.contracts))
            # The "contractId IN" condition matches on autoId, which create_contract
            # does not return — read it back only for this depth.
            auto_ids = await self.contract_provisioner.fetch_contract_auto_ids(bundle.contracts)
            plog.append(f"[contracts] autoIds: {auto_ids}")
            br_setup = await self.br_provisioner.provision_for_contracts(
                _contract_refs(request, bundle.contracts, auto_ids),
                api_key=api_key,
            )
            if api_key:
                rule_configs = {
                    rule_id: data.get("rule_config_id")
                    for rule_id, data in (br_setup.get("rules") or {}).items()
                }
                plog.append(
                    f"[br] existing apiKey {api_key} assigned to the markup rules → "
                    f"ruleConfigs={rule_configs}"
                )
        elif request.provisioning_depth is ProvisioningDepth.full and (
            request.crawla_export or request.sb_config is not None or request.assign_to_br
        ):
            logger.info("Provisioning Business Rules for api_key=%s", api_key)
            br_setup = await self.br_provisioner.provision(api_key, template_id=request.template_id)

        if br_setup is not None:
            bundle.br_setup = br_setup
            br_status = br_setup.get("status", "?")
            br_errors = br_setup.get("errors", [])
            plog.append(f"[br] Provisioning status={br_status} errors={br_errors}")
            if br_status != "SUCCESS":
                bundle.error_message = br_setup.get("warning") or "BR setup failed"
                logger.warning("BR provisioning had errors: %s", bundle.error_message)

        bundle.mock_server_base_url = mock_base
        bundle.status = ScenarioStatus.READY
        plog.append(
            f"[done] Scenario READY depth={request.provisioning_depth.value} "
            f"api_key={api_key or '-'} api_key_id={api_key_id or '-'}"
            f"{' (existing)' if bundle.api_key_is_external else ''}"
        )
        return bundle

    async def refresh_booking_ids(self, request: ScenarioRequest) -> ScenarioBundle:
        built = self.engine.build_expectations(request)
        booking_ids = await refresh_booking_flow_expectations(built)
        return ScenarioBundle(
            namespace=request.namespace,
            status=ScenarioStatus.READY,
            booking_ids=booking_ids,
            check_in=request.check_in,
            check_out=request.check_out,
            atg_hotel_id=request.atg_hotel_id,
            supplier_hotel_ids=request.supplier_hotel_ids,
            mock_server_base_url=self.settings.mock_server_url,
            created_at=datetime.now(timezone.utc),
        )

    async def teardown_scenario(
        self,
        namespace: str,
        *,
        api_key_id: str | None = None,
        api_key: str | None = None,
        br_setup: dict | None = None,
        contracts: dict[str, str] | None = None,
        suppliers: list[str] | None = None,
        sb_group_id: str | None = None,
        sb_config_id: str | None = None,
        api_key_is_external: bool = False,
    ) -> ScenarioBundle:
        if br_setup:
            # cleanup() handles both shapes: apiKey rule-configs/conditions, and the
            # contract conditions created by the contract_br depth.
            await self.br_provisioner.cleanup(
                br_setup, None if api_key_is_external else api_key
            )

        async with MockServerClient() as client:
            await client.delete_by_namespace(namespace, suppliers=suppliers)

        # The apiKey was NOT created by this scenario — it belongs to someone else and
        # must survive. Detach our contracts from it first, so it is never left
        # pointing at a contract we are about to delete.
        if api_key_is_external and api_key and contracts:
            try:
                await self.apikey_provisioner.detach_contracts(api_key, list(contracts.values()))
            except Exception:  # noqa: BLE001 - teardown continues; contracts still get deleted
                logger.exception(
                    "Failed to detach contracts from existing apiKey=%s — it may still "
                    "reference the deleted contracts", api_key,
                )

        if contracts or api_key_id:
            async with BackofficeClient() as backoffice:
                for contract_id in (contracts or {}).values():
                    try:
                        await backoffice.delete_contract(contract_id)
                    except BackofficeError as exc:
                        if "status=404" not in str(exc):
                            raise
                if api_key_id and not api_key_is_external:
                    try:
                        await backoffice.delete_api_key(api_key_id)
                    except BackofficeError as exc:
                        if "status=404" not in str(exc):
                            raise

        # SB teardown — only when sb_group_id present; best-effort, logged on failure
        if sb_group_id and api_key_id:
            node_id = self.settings.tenant_id
            logger.info(
                "Tearing down SB group: group_id=%s config_id=%s api_key_id=%s",
                sb_group_id, sb_config_id, api_key_id,
            )
            await self.sb_group_provisioner.teardown(
                group_id=sb_group_id,
                api_key_id=api_key_id,
                node_id=node_id,
                sb_config_id=sb_config_id,
            )

        return ScenarioBundle(
            namespace=namespace,
            status=ScenarioStatus.TORN_DOWN,
            check_in="",
            check_out="",
            atg_hotel_id="",
            created_at=datetime.now(timezone.utc),
        )
