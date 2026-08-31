"""Create backoffice contracts with MockServer URLs."""

from __future__ import annotations

import copy
import logging
from typing import Any

from app.config import get_settings
from app.core.contract_opt import apply_contract_opt_defaults
from app.core.mock_urls import build_mock_opt_urls
from app.integrations.backoffice import BackofficeClient
from app.models.scenario import ScenarioRequest
from app.models.supplier import SupplierConfig
from app.services.supplier_service import get_supplier_config

#: Priority every SMF contract is created with. Backoffice takes it as a string.
DEFAULT_CONTRACT_PRIORITY = "0"


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
                config = get_supplier_config(supplier_code)
                contract_currency = supplier.contract_currency
                paths = mock_paths.get(instance_key, {})
                # prebook_url=False leaves the contract with no overridePrebookUrl.
                # Independent of the canPrebook permission below: a scenario may want
                # the permission on with no override, or off with one still wired.
                spec = supplier.packages
                opt_urls = build_mock_opt_urls(
                    mock_base_url,
                    paths,
                    supplier_code=supplier_code,
                    include_prebook_url=getattr(spec, "prebook_url", None) is not False,
                )
                body = await self._build_contract_body(
                    config,
                    request.namespace,
                    opt_urls,
                    contract_currency,
                    instance_key=instance_key,
                    permission_overrides=_scenario_permissions(supplier),
                )
                contract_id = await self.backoffice.create_contract(body)
                contract_ids[instance_key] = contract_id
        return contract_ids

    async def fetch_contract_auto_ids(self, contract_ids: dict[str, str]) -> dict[str, str]:
        """{instance_key: autoId} for created contracts.

        The BR "contractId IN" condition matches on the contract's short numeric
        autoId (e.g. 10103), not the mongo _id — and create_contract only surfaces the
        _id. Read it back per contract. Only the contract_br depth needs this, so the
        extra GET is paid there and nowhere else. A contract whose autoId cannot be
        read is omitted rather than guessed at.
        """
        auto_ids: dict[str, str] = {}
        async with self.backoffice:
            for instance_key, contract_id in contract_ids.items():
                try:
                    doc = await self.backoffice.get_contract(contract_id)
                except BackofficeError:
                    logging.getLogger(__name__).exception(
                        "Could not read back contract %s (%s) to get its autoId",
                        instance_key, contract_id,
                    )
                    continue
                auto_id = doc.get("autoId") or doc.get("auto_id")
                if auto_id not in (None, ""):
                    auto_ids[instance_key] = str(auto_id)
        return auto_ids

    async def _build_contract_body(
        self,
        config: SupplierConfig,
        namespace: str,
        opt_urls: dict[str, str],
        contract_currency: str,
        instance_key: str = "",
        permission_overrides: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        instance_key = instance_key or config.code
        reference_id = self._reference_contract_id(config)
        if reference_id:
            reference = await self.backoffice.get_contract(reference_id)
            return _clone_contract(
                reference,
                config,
                namespace,
                opt_urls,
                contract_currency,
                permission_overrides=permission_overrides,
                instance_key=instance_key,
            )
        # No reference contract on the supplier row and none in the env file — the
        # minimal synthesized body may carry a supplier_id connectivity-core rejects
        # with "Cannot find Supplier of id", and search comes back empty (the recurring
        # EXT-contract bug when {SUPPLIER}_REFERENCE_CONTRACT_ID is missing from this
        # machine's .env). Warn loudly rather than silently building a broken contract.
        logging.getLogger(__name__).warning(
            "No reference contract for %s in env=%s — set one on the Suppliers screen, "
            "or %s_REFERENCE_CONTRACT_ID in backend/.env.%s. Falling back to a minimal "
            "contract body, which connectivity-core will likely reject (empty search).",
            config.code,
            getattr(self.settings, "env", "?"),
            config.code,
            getattr(self.settings, "env", "?") or "<env>",
        )
        return _minimal_contract_body(
            config,
            namespace,
            opt_urls,
            self.settings.mock_server_url,
            contract_currency,
            instance_key=instance_key,
            permission_overrides=permission_overrides,
        )

    def _reference_contract_id(self, config: SupplierConfig) -> str:
        """The supplier's reference contract, its row first then the env file.

        The Suppliers screen owns this value now, but ``<CODE>_REFERENCE_CONTRACT_ID``
        stays a fallback so an existing .env keeps working for a supplier whose row has
        never been given one.
        """
        if config.reference_contract_id:
            return config.reference_contract_id
        return getattr(self.settings, f"{config.code.lower()}_reference_contract_id", "") or ""


def _scenario_permissions(supplier) -> dict[str, bool]:
    """Contract permissions this scenario pins, or {} when it pins none.

    Only fields the scenario actually set appear — an unset can_prebook leaves the
    reference contract's own value alone, which is the pre-existing behaviour.
    """
    spec = getattr(supplier, "packages", None)
    can_prebook = getattr(spec, "can_prebook", None) if spec is not None else None
    return {} if can_prebook is None else {"canPrebook": can_prebook}


def _clone_contract(
    reference: dict[str, Any],
    config: SupplierConfig,
    namespace: str,
    opt_urls: dict[str, str],
    contract_currency: str,
    permission_overrides: dict[str, bool] | None = None,
    instance_key: str = "",
) -> dict[str, Any]:
    body = copy.deepcopy(reference)
    for key in ("_id", "id", "autoId", "createdAt", "updatedAt", "__v"):
        body.pop(key, None)
    instance_key = instance_key or config.code
    uid = _contract_uid(namespace, instance_key)
    body["uid"] = uid
    body["label"] = f"SMF {namespace} {instance_key}"
    # Never inherited from the reference: package-merge breaks price ties on contract
    # priority, and the reference contracts do not agree (HBS's carries 1 where the others
    # carry 0). A cloned contract that keeps that would quietly win every tie against the
    # other suppliers in the same scenario, which reads as a merge bug rather than a
    # contract difference. Every SMF contract sits at the same priority.
    body["priority"] = DEFAULT_CONTRACT_PRIORITY
    _apply_dynamic_market_type(body, config)
    opt = body.setdefault("opt", {})
    if isinstance(opt, dict):
        opt.update(opt_urls)
        # One config-driven call in place of the per-supplier apply_*_contract_opt_defaults
        # chain: which keys to fill, force, and whether to stamp mockServerUrl are
        # MockConfig fields on the supplier row.
        apply_contract_opt_defaults(opt, config.mock_config, get_settings().mock_server_url)
    _apply_forced_permission(body, config)
    _apply_scenario_permission(body, permission_overrides or {})
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
    instance_key: str = "",
    permission_overrides: dict[str, bool] | None = None,
) -> dict[str, Any]:
    instance_key = instance_key or config.code
    uid = _contract_uid(namespace, instance_key)
    enabled_currencies = [contract_currency, *(c for c in ("SAR", "AED", "USD", "EUR") if c != contract_currency)]
    body = {
        "code": config.code,
        "uid": uid,
        "label": f"SMF {namespace} {instance_key}",
        "userName": uid,
        "password": "smf-password",
        "priority": DEFAULT_CONTRACT_PRIORITY,
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
    _apply_forced_permission(body, config)
    _apply_scenario_permission(body, permission_overrides or {})
    return body


def contract_uid(namespace: str, instance_key: str) -> str:
    """Public alias — the BR contract conditions may key on the contract uid, which is
    deterministic from (namespace, instance key) and so derivable without a re-read."""
    return _contract_uid(namespace, instance_key)


def _contract_uid(namespace: str, instance_key: str) -> str:
    """`instance_key` is the supplier code for a single entry, or "EXP-2" for a
    repeated one — the uid must differ or backoffice rejects the second contract."""
    return f"smf-{namespace}-{instance_key}".lower().replace(" ", "-")


def _permission_block(body: dict[str, Any]) -> dict[str, Any]:
    permission = body.get("permission")
    if not isinstance(permission, dict):
        permission = {}
        body["permission"] = permission
    return permission


def _write_permission(permission: dict[str, Any], key: str, value: Any) -> None:
    """Set one permission flag in the shape the block already uses.

    These flags come back from Backoffice as the strings "true"/"false" on a clone but as
    real booleans on a minimal body, and mixing the two risks the whole block being
    misread. Matching the key's own current type covers a key that is already there.

    A key that is ABSENT has no type to match, so take the shape from its siblings —
    EXT's reference contract has no canPrebook at all, and writing a bare boolean into a
    block of "true"/"false" strings produced exactly the mixed block this guards against.
    An empty block has nothing to infer from and keeps the native bool.
    """
    if not isinstance(value, bool):
        permission[key] = value
        return
    current = permission.get(key)
    if current is None:
        stringly = any(isinstance(other, str) for other in permission.values())
    else:
        stringly = isinstance(current, str)
    permission[key] = ("true" if value else "false") if stringly else value


def _apply_scenario_permission(body: dict[str, Any], overrides: dict[str, bool]) -> None:
    """Per-scenario permission overrides, applied AFTER the supplier's forced ones.

    The scenario is the more specific intent: a supplier may force canPrebook true for
    every contract, but this run may still want it off.
    """
    if not overrides:
        return
    permission = _permission_block(body)
    for key, value in overrides.items():
        _write_permission(permission, key, value)


def _apply_forced_permission(body: dict[str, Any], config: SupplierConfig) -> None:
    """Override contract permission flags the supplier's config pins.

    A cloned reference contract brings its own permissions, and a safe reference
    (Hilton's is named "…-dont-book-…") carries canBook false — which refuses the
    booking flow upstream of the mock. EXT's carries no canPrebook at all, so its clones
    permit no price check.
    """
    forced = config.mock_config.forced_permission
    if not forced:
        return
    permission = _permission_block(body)
    for key, value in forced.items():
        _write_permission(permission, key, value)


def _apply_dynamic_market_type(body: dict[str, Any], config: SupplierConfig) -> None:
    """Net suppliers receive the borrowed market price (DynamicMarkupTarget); gross
    suppliers provide it (MarketPriceSource). Without this a net supplier inherits the
    reference contract's "NotParticipating" and is left out of merge. Suppliers with
    no configured value (RHK) keep whatever the reference contract carried."""
    if config.mock_config.dynamic_market_type:
        body["dynamicMarketType"] = config.mock_config.dynamic_market_type
