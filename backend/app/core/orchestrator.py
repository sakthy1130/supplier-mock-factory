"""Main pipeline: templates → mocks → contracts → apiKey."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.core.apikey_provisioner import ApiKeyProvisioner
from app.core.contract_provisioner import ContractProvisioner
from app.core.mock_registration import refresh_booking_flow_expectations, register_built_expectations
from app.core.mock_urls import extract_paths_from_built
from app.core.scenario_engine import ScenarioEngine
from app.integrations.business_rules import CrawlaBusinessRulesProvisioner
from app.integrations.backoffice import BackofficeClient, BackofficeError
from app.integrations.mock_server import MockServerClient
from app.models.scenario import ScenarioBundle, ScenarioRequest, ScenarioStatus


class SupplierMockScenarioOrchestrator:
    """Coordinates scenario creation end-to-end."""

    def __init__(
        self,
        engine: ScenarioEngine | None = None,
        contract_provisioner: ContractProvisioner | None = None,
        apikey_provisioner: ApiKeyProvisioner | None = None,
        br_provisioner: CrawlaBusinessRulesProvisioner | None = None,
    ) -> None:
        self.engine = engine or ScenarioEngine()
        self.contract_provisioner = contract_provisioner or ContractProvisioner()
        self.apikey_provisioner = apikey_provisioner or ApiKeyProvisioner()
        self.br_provisioner = br_provisioner or CrawlaBusinessRulesProvisioner()
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

        built = self.engine.build_expectations(request)
        bundle.expectation_count = len(built)

        bundle.status = ScenarioStatus.REGISTERING
        bundle.booking_ids = await register_built_expectations(built)

        mock_paths = extract_paths_from_built(built)
        mock_base = self.settings.mock_server_url

        bundle.status = ScenarioStatus.CREATING_CONTRACTS
        bundle.contracts = await self.contract_provisioner.create_contracts(
            request,
            mock_paths,
            mock_base,
        )

        bundle.status = ScenarioStatus.CREATING_API_KEY
        api_key, api_key_id = await self.apikey_provisioner.create_api_key(
            bundle.contracts,
            request.namespace,
        )
        bundle.api_key = api_key
        bundle.api_key_id = api_key_id
        if request.crawla_export:
            br_setup = await self.br_provisioner.provision(api_key)
            bundle.br_setup = br_setup
            if br_setup.get("status") != "SUCCESS":
                bundle.error_message = br_setup.get("warning") or "BR setup failed"
        bundle.mock_server_base_url = mock_base
        bundle.status = ScenarioStatus.READY
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

        return ScenarioBundle(
            namespace=namespace,
            status=ScenarioStatus.TORN_DOWN,
            check_in="",
            check_out="",
            atg_hotel_id="",
            created_at=datetime.now(timezone.utc),
        )
