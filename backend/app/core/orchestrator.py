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
from app.models.scenario import ScenarioBundle, ScenarioRequest, ScenarioStatus

logger = logging.getLogger(__name__)


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

        # Step 3a: Create SB group BEFORE SB configuration and apiKey
        sb_config_data: dict | None = None
        sb_group_data: dict | None = None
        if request.sb_config is not None:
            node_id = self.settings.tenant_id
            logger.info("Creating SB group for namespace=%s", request.namespace)
            sb_group_data = await self.sb_group_provisioner.create_group(
                namespace=request.namespace,
                contract_ids=list(bundle.contracts.values()),
            )
            bundle.sb_group_id = sb_group_data["_id"]
            bundle.sb_group_name = sb_group_data["name"]
            plog.append(
                f"[sb_group] POST /api/dynamic-forms/smart_booking_group → "
                f"_id={sb_group_data['_id']} name={sb_group_data['name']} "
                f"contracts={list(bundle.contracts.values())}"
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

        # Step 4: Create apiKey and attach contracts (cache cleared inside provisioner)
        bundle.status = ScenarioStatus.CREATING_API_KEY
        api_key, api_key_id = await self.apikey_provisioner.create_api_key(
            bundle.contracts,
            request.namespace,
            prov_log=plog,
        )
        bundle.api_key = api_key
        bundle.api_key_id = api_key_id

        # Step 5: Assign SB config + group to apiKey as opt.smartBooking, clear cache
        if request.sb_config is not None and sb_config_data is not None and sb_group_data is not None:
            node_id = self.settings.tenant_id
            await self.sb_group_provisioner.assign_to_api_key(
                api_key_id=api_key_id,
                api_key=api_key,
                node_id=node_id,
                sb_config_data=sb_config_data,
                sb_group_data=sb_group_data,
                sb_config=request.sb_config,
                prov_log=plog,
            )
            logger.info(
                "SB config+group attached and cache cleared: api_key=%s "
                "sb_config_id=%s sb_group_id=%s",
                api_key, sb_config_data["_id"], sb_group_data["_id"],
            )

        # Step 6: BR provisioning — for crawla_export AND for all SB scenarios
        if request.crawla_export or request.sb_config is not None:
            logger.info("Provisioning Business Rules for api_key=%s", api_key)
            br_setup = await self.br_provisioner.provision(api_key)
            bundle.br_setup = br_setup
            br_status = br_setup.get("status", "?")
            br_errors = br_setup.get("errors", [])
            plog.append(f"[br] Provisioning status={br_status} errors={br_errors}")
            if br_status != "SUCCESS":
                bundle.error_message = br_setup.get("warning") or "BR setup failed"
                logger.warning("BR provisioning had errors: %s", bundle.error_message)

        bundle.mock_server_base_url = mock_base
        bundle.status = ScenarioStatus.READY
        plog.append(f"[done] Scenario READY api_key={api_key} api_key_id={api_key_id}")
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
    ) -> ScenarioBundle:
        if br_setup:
            await self.br_provisioner.cleanup(br_setup, api_key)

        async with MockServerClient() as client:
            await client.delete_by_namespace(namespace, suppliers=suppliers)

        if contracts or api_key_id:
            async with BackofficeClient() as backoffice:
                for contract_id in (contracts or {}).values():
                    try:
                        await backoffice.delete_contract(contract_id)
                    except BackofficeError as exc:
                        if "status=404" not in str(exc):
                            raise
                if api_key_id:
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
