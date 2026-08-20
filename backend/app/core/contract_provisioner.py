"""Create backoffice contracts with MockServer URLs."""

from __future__ import annotations

import copy
from typing import Any

from app.config import get_settings
from app.core.contract_opt import apply_contract_opt_defaults
from app.core.mock_urls import build_mock_opt_urls
from app.integrations.backoffice import BackofficeClient
from app.models.scenario import ScenarioRequest
from app.models.supplier import SupplierConfig
from app.services.supplier_service import get_supplier_config


class ContractProvisioner:
    def __init__(self, backoffice: BackofficeClient | None = None) -> None:
        self.backoffice = backoffice or BackofficeClient()
        self.settings = get_settings()

    async def create_contracts(
        self,
        request: ScenarioRequest,
        mock_paths: dict[str, dict[str, str]],
        mock_base_url: str,
    ) -> dict[str, str]:
        contract_ids: dict[str, str] = {}
        async with self.backoffice:
            for supplier in request.suppliers:
                supplier_code = str(supplier.code)
                config = get_supplier_config(supplier_code)
                contract_currency = supplier.contract_currency
                paths = mock_paths.get(supplier_code, {})
                opt_urls = build_mock_opt_urls(mock_base_url, paths, supplier_code=supplier_code)
                body = await self._build_contract_body(
                    config, request.namespace, opt_urls, contract_currency
                )
                contract_id = await self.backoffice.create_contract(body)
                contract_ids[supplier_code] = contract_id
        return contract_ids

    def _reference_contract_id(self, config: SupplierConfig) -> str:
        """The supplier's reference contract, config first then the env file.

        The Suppliers screen owns this value now, but ``<CODE>_REFERENCE_CONTRACT_ID``
        stays a fallback so an existing .env keeps working for a supplier whose row has
        never been given one.
        """
        if config.reference_contract_id:
            return config.reference_contract_id
        return getattr(self.settings, f"{config.code.lower()}_reference_contract_id", "") or ""

    async def _build_contract_body(
        self,
        config: SupplierConfig,
        namespace: str,
        opt_urls: dict[str, str],
        contract_currency: str,
    ) -> dict[str, Any]:
        reference_id = self._reference_contract_id(config)
        if reference_id:
            reference = await self.backoffice.get_contract(reference_id)
            return _clone_contract(reference, config, namespace, opt_urls, contract_currency)
        return _minimal_contract_body(
            config, namespace, opt_urls, self.settings.mock_server_url, contract_currency
        )


def _clone_contract(
    reference: dict[str, Any],
    config: SupplierConfig,
    namespace: str,
    opt_urls: dict[str, str],
    contract_currency: str,
) -> dict[str, Any]:
    body = copy.deepcopy(reference)
    for key in ("_id", "id", "autoId", "createdAt", "updatedAt", "__v"):
        body.pop(key, None)
    uid = _contract_uid(namespace, config.code)
    body["uid"] = uid
    body["label"] = f"SMF {namespace} {config.code}"
    _apply_dynamic_market_type(body, config)
    opt = body.setdefault("opt", {})
    if isinstance(opt, dict):
        opt.update(opt_urls)
        apply_contract_opt_defaults(opt, config.mock_config, get_settings().mock_server_url)
    # Apply contract currency to all suppliers (not just CHC)
    body["currency"] = contract_currency
    supported = body.get("supportedCurrencies", [])
    if not isinstance(supported, list):
        supported = []
    if contract_currency not in supported:
        supported = [contract_currency, *supported]
    body["supportedCurrencies"] = supported
    return body


def _minimal_contract_body(
    config: SupplierConfig,
    namespace: str,
    opt_urls: dict[str, str],
    mock_base_url: str,
    contract_currency: str,
) -> dict[str, Any]:
    uid = _contract_uid(namespace, config.code)
    enabled_currencies = [contract_currency, *(c for c in ("SAR", "AED", "USD", "EUR") if c != contract_currency)]
    body = {
        "code": config.code,
        "uid": uid,
        "label": f"SMF {namespace} {config.code}",
        "userName": uid,
        "password": "smf-password",
        "priority": "1",
        "supplierId": config.supplier_id,
        "supplierDetail": config.supplier_detail,
        "supplierType": config.supplier_type,
        "timeoutSeconds": "60",
        "baseApiUrl": mock_base_url.rstrip("/"),
        "currency": contract_currency,
        "supplierAutoId": str(config.auto_id),
        "enabledCurrencyArr": enabled_currencies,
        "supplierSupportedCurrencies": enabled_currencies,
        "opt": apply_contract_opt_defaults(dict(opt_urls), config.mock_config, mock_base_url),
        "permission": {
            "isEnable": True,
            "canSearch": True,
            "canBook": True,
            "canCancel": True,
            "canCancellationPolicies": True,
            "canPackages": True,
            "canOrder": True,
        },
    }
    _apply_dynamic_market_type(body, config)
    return body


def _contract_uid(namespace: str, supplier_code: str) -> str:
    return f"smf-{namespace}-{supplier_code}".lower().replace(" ", "-")


def _apply_dynamic_market_type(body: dict[str, Any], config: SupplierConfig) -> None:
    """Net suppliers receive the borrowed market price (DynamicMarkupTarget); gross
    suppliers provide it (MarketPriceSource). Without this a net supplier inherits the
    reference contract's "NotParticipating" and is left out of merge. Suppliers with
    no configured value (RHK) keep whatever the reference contract carried."""
    if config.mock_config.dynamic_market_type:
        body["dynamicMarketType"] = config.mock_config.dynamic_market_type
