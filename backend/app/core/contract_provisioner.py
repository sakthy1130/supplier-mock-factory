"""Create backoffice contracts with MockServer URLs."""

from __future__ import annotations

import copy
from typing import Any

from app.config import get_settings
from app.core.exp_paths import apply_exp_contract_opt_defaults
from app.core.hbs_paths import apply_hbs_contract_opt_defaults
from app.core.mock_urls import build_mock_opt_urls
from app.core.supplier_registry import SUPPLIER_REGISTRY
from app.integrations.backoffice import BackofficeClient
from app.models.scenario import ScenarioRequest


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
                supplier_code = supplier.code.value
                paths = mock_paths.get(supplier_code, {})
                opt_urls = build_mock_opt_urls(mock_base_url, paths, supplier_code=supplier_code)
                body = await self._build_contract_body(supplier_code, request.namespace, opt_urls)
                contract_id = await self.backoffice.create_contract(body)
                contract_ids[supplier_code] = contract_id
        return contract_ids

    async def _build_contract_body(
        self,
        supplier_code: str,
        namespace: str,
        opt_urls: dict[str, str],
    ) -> dict[str, Any]:
        reference_id = self._reference_contract_id(supplier_code)
        if reference_id:
            reference = await self.backoffice.get_contract(reference_id)
            return _clone_contract(reference, supplier_code, namespace, opt_urls)
        return _minimal_contract_body(supplier_code, namespace, opt_urls, self.settings.mock_server_url)

    def _reference_contract_id(self, supplier_code: str) -> str:
        if supplier_code == "HBS":
            return self.settings.hbs_reference_contract_id
        if supplier_code == "EXP":
            return self.settings.exp_reference_contract_id
        if supplier_code == "RHK":
            return self.settings.rhk_reference_contract_id
        return ""


def _clone_contract(
    reference: dict[str, Any],
    supplier_code: str,
    namespace: str,
    opt_urls: dict[str, str],
) -> dict[str, Any]:
    body = copy.deepcopy(reference)
    for key in ("_id", "id", "autoId", "createdAt", "updatedAt", "__v"):
        body.pop(key, None)
    uid = _contract_uid(namespace, supplier_code)
    body["uid"] = uid
    body["label"] = f"SMF {namespace} {supplier_code}"
    _apply_hbs_contract_defaults(body, supplier_code)
    opt = body.setdefault("opt", {})
    if isinstance(opt, dict):
        opt.update(opt_urls)
        if supplier_code == "HBS":
            apply_hbs_contract_opt_defaults(opt, get_settings().mock_server_url)
        elif supplier_code == "EXP":
            apply_exp_contract_opt_defaults(opt, get_settings().mock_server_url)
    return body


def _minimal_contract_body(
    supplier_code: str,
    namespace: str,
    opt_urls: dict[str, str],
    mock_base_url: str,
) -> dict[str, Any]:
    meta = SUPPLIER_REGISTRY[supplier_code]
    uid = _contract_uid(namespace, supplier_code)
    body = {
        "code": meta["code"],
        "uid": uid,
        "label": f"SMF {namespace} {supplier_code}",
        "userName": uid,
        "password": "smf-password",
        "priority": "1",
        "supplierId": meta["supplier_id"],
        "supplierDetail": meta["supplier_detail"],
        "supplierType": meta["supplier_type"],
        "timeoutSeconds": "60",
        "baseApiUrl": mock_base_url.rstrip("/"),
        "currency": "SAR",
        "supplierAutoId": str(meta["auto_id"]),
        "enabledCurrencyArr": ["SAR", "AED", "USD", "EUR"],
        "supplierSupportedCurrencies": ["SAR", "AED", "USD", "EUR"],
        "opt": (
            apply_hbs_contract_opt_defaults(dict(opt_urls), mock_base_url)
            if supplier_code == "HBS"
            else apply_exp_contract_opt_defaults(dict(opt_urls), mock_base_url)
            if supplier_code == "EXP"
            else dict(opt_urls)
        ),
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
    _apply_hbs_contract_defaults(body, supplier_code)
    return body


def _contract_uid(namespace: str, supplier_code: str) -> str:
    return f"smf-{namespace}-{supplier_code}".lower().replace(" ", "-")


def _apply_hbs_contract_defaults(body: dict[str, Any], supplier_code: str) -> None:
    if supplier_code == "HBS":
        body["dynamicMarketType"] = "DynamicMarkupTarget"
    elif supplier_code == "EXP":
        body["dynamicMarketType"] = "MarketPriceSource"
