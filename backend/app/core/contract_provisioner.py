"""Create backoffice contracts with MockServer URLs."""

from __future__ import annotations

import copy
import logging
from typing import Any

from app.config import get_settings
from app.core.chc_paths import apply_chc_contract_opt_defaults
from app.core.exp_paths import apply_exp_contract_opt_defaults
from app.core.ext_paths import apply_ext_contract_opt_defaults
from app.core.hbs_paths import apply_hbs_contract_opt_defaults
from app.core.mock_urls import build_mock_opt_urls
from app.core.supplier_registry import get_supplier_registry
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
                # One contract per supplier ENTRY, keyed by instance: a scenario with
                # two EXP entries gets two contracts ("EXP" and "EXP-2"), each wired
                # to its own mock paths.
                instance_key = supplier.instance_key
                contract_currency = supplier.contract_currency
                paths = mock_paths.get(instance_key, {})
                opt_urls = build_mock_opt_urls(mock_base_url, paths, supplier_code=supplier_code)
                body = await self._build_contract_body(
                    supplier_code,
                    request.namespace,
                    opt_urls,
                    contract_currency,
                    instance_key=instance_key,
                )
                contract_id = await self.backoffice.create_contract(body)
                contract_ids[instance_key] = contract_id
        return contract_ids

    async def _build_contract_body(
        self,
        supplier_code: str,
        namespace: str,
        opt_urls: dict[str, str],
        contract_currency: str,
        instance_key: str = "",
    ) -> dict[str, Any]:
        instance_key = instance_key or supplier_code
        reference_id = self._reference_contract_id(supplier_code)
        if reference_id:
            reference = await self.backoffice.get_contract(reference_id)
            return _clone_contract(
                reference,
                supplier_code,
                namespace,
                opt_urls,
                contract_currency,
                instance_key=instance_key,
            )
        # No reference id configured for this supplier — the minimal synthesized
        # body carries a wrong supplier_id, so connectivity-core rejects it with
        # "Cannot find Supplier of id" and search comes back empty (the recurring
        # EXT-contract bug when {SUPPLIER}_REFERENCE_CONTRACT_ID is missing from
        # this machine's .env). Warn loudly so the misconfig is obvious instead of
        # silently producing a broken contract.
        logging.getLogger(__name__).warning(
            "No %s_REFERENCE_CONTRACT_ID set for env=%s — falling back to a minimal "
            "contract body, which connectivity-core will likely reject (empty search). "
            "Set %s_REFERENCE_CONTRACT_ID in backend/.env.%s.",
            supplier_code,
            getattr(self.settings, "env", "?"),
            supplier_code,
            getattr(self.settings, "env", "?") or "<env>",
        )
        return _minimal_contract_body(
            supplier_code,
            namespace,
            opt_urls,
            self.settings.mock_server_url,
            contract_currency,
            instance_key=instance_key,
        )

    def _reference_contract_id(self, supplier_code: str) -> str:
        if supplier_code == "HBS":
            return self.settings.hbs_reference_contract_id
        if supplier_code == "EXP":
            return self.settings.exp_reference_contract_id
        if supplier_code == "RHK":
            return self.settings.rhk_reference_contract_id
        if supplier_code == "CHC":
            return self.settings.chc_reference_contract_id
        if supplier_code == "EXT":
            return self.settings.ext_reference_contract_id
        return ""


def _clone_contract(
    reference: dict[str, Any],
    supplier_code: str,
    namespace: str,
    opt_urls: dict[str, str],
    contract_currency: str,
    instance_key: str = "",
) -> dict[str, Any]:
    body = copy.deepcopy(reference)
    for key in ("_id", "id", "autoId", "createdAt", "updatedAt", "__v"):
        body.pop(key, None)
    instance_key = instance_key or supplier_code
    uid = _contract_uid(namespace, instance_key)
    body["uid"] = uid
    body["label"] = f"SMF {namespace} {instance_key}"
    _apply_hbs_contract_defaults(body, supplier_code)
    opt = body.setdefault("opt", {})
    if isinstance(opt, dict):
        opt.update(opt_urls)
        if supplier_code == "HBS":
            apply_hbs_contract_opt_defaults(opt, get_settings().mock_server_url)
        elif supplier_code == "EXP":
            apply_exp_contract_opt_defaults(opt, get_settings().mock_server_url)
        elif supplier_code == "CHC":
            apply_chc_contract_opt_defaults(opt, get_settings().mock_server_url)
        elif supplier_code == "EXT":
            apply_ext_contract_opt_defaults(opt, get_settings().mock_server_url)
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
    supplier_code: str,
    namespace: str,
    opt_urls: dict[str, str],
    mock_base_url: str,
    contract_currency: str,
    instance_key: str = "",
) -> dict[str, Any]:
    meta = get_supplier_registry()[supplier_code]
    instance_key = instance_key or supplier_code
    uid = _contract_uid(namespace, instance_key)
    enabled_currencies = [contract_currency, *(c for c in ("SAR", "AED", "USD", "EUR") if c != contract_currency)]
    body = {
        "code": meta["code"],
        "uid": uid,
        "label": f"SMF {namespace} {instance_key}",
        "userName": uid,
        "password": "smf-password",
        "priority": "1",
        "supplierId": meta["supplier_id"],
        "supplierDetail": meta["supplier_detail"],
        "supplierType": meta["supplier_type"],
        "timeoutSeconds": "60",
        "baseApiUrl": mock_base_url.rstrip("/"),
        "currency": contract_currency,
        "supplierAutoId": str(meta["auto_id"]),
        "enabledCurrencyArr": enabled_currencies,
        "supplierSupportedCurrencies": enabled_currencies,
        "opt": (
            apply_hbs_contract_opt_defaults(dict(opt_urls), mock_base_url)
            if supplier_code == "HBS"
            else apply_exp_contract_opt_defaults(dict(opt_urls), mock_base_url)
            if supplier_code == "EXP"
            else apply_chc_contract_opt_defaults(dict(opt_urls), mock_base_url)
            if supplier_code == "CHC"
            else apply_ext_contract_opt_defaults(dict(opt_urls), mock_base_url)
            if supplier_code == "EXT"
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


def contract_uid(namespace: str, instance_key: str) -> str:
    """Public alias — the BR contract conditions may key on the contract uid, which is
    deterministic from (namespace, instance key) and so derivable without a re-read."""
    return _contract_uid(namespace, instance_key)


def _contract_uid(namespace: str, instance_key: str) -> str:
    """`instance_key` is the supplier code for a single entry, or "EXP-2" for a
    repeated one — the uid must differ or backoffice rejects the second contract."""
    return f"smf-{namespace}-{instance_key}".lower().replace(" ", "-")


def _apply_hbs_contract_defaults(body: dict[str, Any], supplier_code: str) -> None:
    # Net suppliers receive the borrowed market price (DynamicMarkupTarget); gross
    # suppliers provide it (MarketPriceSource). CHC and EXT are net like HBS — without this it
    # inherits the reference contract's "NotParticipating" and is left out of merge.
    if supplier_code in ("HBS", "CHC", "EXT"):
        body["dynamicMarketType"] = "DynamicMarkupTarget"
    elif supplier_code == "EXP":
        body["dynamicMarketType"] = "MarketPriceSource"
