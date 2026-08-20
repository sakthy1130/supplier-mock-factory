"""Create new apiKey per scenario and attach contracts."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from app.config import get_settings
from app.integrations.backoffice import BackofficeClient, BackofficeError
from app.integrations.config_manager import ConfigManagerClient

logger = logging.getLogger(__name__)

DEFAULT_API_KEY_TEMPLATE = "tj-htl-test-bookable"


class ApiKeyProvisioner:
    def __init__(
        self,
        backoffice: BackofficeClient | None = None,
        config_manager: ConfigManagerClient | None = None,
    ) -> None:
        self.backoffice = backoffice or BackofficeClient()
        self.config_manager = config_manager or ConfigManagerClient(self.backoffice)
        self.settings = get_settings()

    async def create_api_key(
        self,
        contract_ids: dict[str, str],
        namespace: str,
        sb_config_data: dict[str, Any] | None = None,
        sb_group_data: dict[str, Any] | None = None,
        sb_enabled: bool = True,
        prov_log: list[str] | None = None,
    ) -> tuple[str, str]:
        api_key = _api_key_value(namespace)
        node_id = self.settings.tenant_id
        if not node_id:
            raise ValueError("TENANT_ID is required to provision apiKey")

        def _plog(msg: str) -> None:
            logger.info(msg)
            if prov_log is not None:
                prov_log.append(msg)

        async with self.backoffice:
            template_name = self.settings.api_key_template_uid or DEFAULT_API_KEY_TEMPLATE
            summary = await self.backoffice.find_api_key_by_uid(template_name)
            if not summary or not summary.get("_id"):
                raise BackofficeError(f"ApiKey template not found: {template_name}")

            _plog(f"[apiKey TEMPLATE] fetching template uid={template_name} _id={summary['_id']}")
            template = await self.backoffice.get_api_key_config(str(summary["_id"]), node_id)
            contract_list = _ordered_contract_ids(contract_ids)
            body = _build_api_key_body(
                template,
                api_key,
                node_id,
                contract_list,
                sb_config_data=sb_config_data,
                sb_group_data=sb_group_data,
                sb_enabled=sb_enabled,
            )

            # Get token now so we can build the curl before making the request
            token = await self.backoffice.ensure_token()
            base_url = self.backoffice.base_url
            full_body_json = json.dumps(body, default=str)

            # Log equivalent curl — copy-paste directly into terminal to reproduce
            curl_cmd = (
                f"curl -X POST '{base_url}/api/node/user' "
                f"-H 'Authorization: Bearer {token}' "
                f"-H 'Content-Type: application/json' "
                f"-H 'x-tenant: {node_id}' "
                f"-d '{full_body_json}'"
            )
            _plog(f"[apiKey CREATE CURL] {curl_cmd}")

            created = await self.backoffice.create_api_key(body)
            full_resp_json = json.dumps(created, default=str)
            _plog(f"[apiKey CREATE] → FULL_RESPONSE={full_resp_json}")

            api_key_id = str(created.get("_id") or created.get("id") or "")
            api_key = str(created.get("apikey") or created.get("uid") or api_key)
            if not api_key_id:
                raise ValueError("Create apiKey response missing _id")

            # NOTE: contracts and opt.smartBooking are already set in the create body.
            # Do NOT do a follow-up get_api_key_config + update_api_key here — the GET
            # returns the read-config shape, and PUTting that shape back corrupts the
            # record (portal GET then returns 500). The raw create curl works precisely
            # because it does not do this round-trip.

            await self.config_manager.clear_api_key_cache(api_key)
            _plog(f"[cache clear] POST /api/v1/cache/config/clear/{api_key} → 200 OK")

            return api_key, api_key_id


    async def attach_contracts(
        self,
        api_key: str,
        contract_ids: list[str],
        prov_log: list[str] | None = None,
    ) -> str:
        """Add contract ids to an EXISTING apiKey, returning its backoffice id.

        Used by the contract_only / contract_br depths when the caller supplies an
        apiKey instead of having one created. Contracts are unioned in, never
        replaced — this is someone else's apiKey and it may already carry others.
        """
        return await self._rewrite_contracts(api_key, add=contract_ids, remove=[], prov_log=prov_log)

    async def detach_contracts(
        self,
        api_key: str,
        contract_ids: list[str],
        prov_log: list[str] | None = None,
    ) -> str:
        """Remove contract ids from an existing apiKey (teardown counterpart).

        Runs BEFORE the contracts themselves are deleted, so the apiKey is never
        left referencing a contract that no longer exists.
        """
        return await self._rewrite_contracts(api_key, add=[], remove=contract_ids, prov_log=prov_log)

    async def _rewrite_contracts(
        self,
        api_key: str,
        add: list[str],
        remove: list[str],
        prov_log: list[str] | None = None,
    ) -> str:
        node_id = self.settings.tenant_id
        if not node_id:
            raise ValueError("TENANT_ID is required to update an apiKey")

        def _plog(msg: str) -> None:
            logger.info(msg)
            if prov_log is not None:
                prov_log.append(msg)

        async with self.backoffice:
            summary = await self.backoffice.find_api_key_by_uid(api_key)
            if not summary or not summary.get("_id"):
                raise BackofficeError(f"ApiKey not found: {api_key}")
            api_key_id = str(summary["_id"])

            config = await self.backoffice.get_api_key_config(api_key_id, node_id)
            body, current = _writable_api_key_body(config)
            updated = [cid for cid in current if cid not in set(remove)]
            for contract_id in add:
                if contract_id not in updated:
                    updated.append(contract_id)
            body["contracts"] = updated
            _plog(
                f"[apiKey ATTACH] uid={api_key} _id={api_key_id} "
                f"contracts {current} -> {updated} (+{add} -{remove})"
            )

            await self.backoffice.update_api_key(api_key_id, node_id, body)
            await self.config_manager.clear_api_key_cache(api_key)
            _plog(f"[cache clear] POST /api/v1/cache/config/clear/{api_key} → 200 OK")
        return api_key_id


# Fields the GET config response carries that the PUT endpoint must NOT receive back.
# Echoing the read shape verbatim corrupts the record — the portal then 500s on GET.
# This list mirrors the proven recipe in qaBackend_Enigma's UpdateConfigForRebooker.
_READ_ONLY_API_KEY_FIELDS = (
    "_id",
    "created_at",
    "update_at",
    "updated_at",
    "createdBy",
    "updatedBy",
    "userDetail",
    "nodeDetail",
)


def _writable_api_key_body(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(PUT-safe body, current contract ids) from a GET apiKey config response.

    The GET response expands `contracts` into full objects; the PUT endpoint expects
    a plain list of ids. Returning the ids separately keeps the caller's union/remove
    logic honest about what was already there.
    """
    body = copy.deepcopy(config)
    for field in _READ_ONLY_API_KEY_FIELDS:
        body.pop(field, None)

    current: list[str] = []
    for entry in config.get("contracts") or []:
        if isinstance(entry, dict):
            contract_id = entry.get("_id") or entry.get("id")
            if contract_id:
                current.append(str(contract_id))
        elif entry:
            current.append(str(entry))
    body["contracts"] = current
    return body, current


def _api_key_value(namespace: str) -> str:
    return f"smf-{namespace}".lower().replace(" ", "-")


def _ordered_contract_ids(contract_ids: dict[str, str]) -> list[str]:
    ordered: list[str] = []
    for code in ("HBS", "EXP"):
        if code in contract_ids:
            ordered.append(contract_ids[code])
    for code, contract_id in contract_ids.items():
        if code not in ("HBS", "EXP"):
            ordered.append(contract_id)
    return ordered


def _disable_inherited_smart_booking(opt: dict[str, Any]) -> None:
    """Turn off any SmartBooking carried over from the template apiKey.

    Keeps the block's shape (backoffice stores it on every apiKey) but forces it
    inert: disabled and with no groups attached, so the scenario cannot route
    through another team's standing SB groups.
    """
    smart_booking = opt.get("smartBooking")
    if not isinstance(smart_booking, dict):
        return
    smart_booking["isEnabled"] = False
    smart_booking["groups"] = []


def _build_api_key_body(
    template: dict[str, Any],
    api_key: str,
    node_id: str,
    contract_ids: list[str],
    sb_config_data: dict[str, Any] | None = None,
    sb_group_data: dict[str, Any] | None = None,
    sb_enabled: bool = True,
) -> dict[str, Any]:
    """Build the POST /api/node/user create body.

    The create endpoint expects an explicit, flat body (the shape the Backoffice
    portal stores), NOT the GET-config response shape. Cloning the full GET
    response produced records the portal could not open. We source the proven
    `opt` block from the template but construct a clean top-level body, and
    inject SB configuration + groups into `opt.smartBooking` at create time.
    """
    opt = copy.deepcopy(template.get("opt", {}))

    # Drop stale flat SB fields that older code may have written.
    for stale in ("smartBook", "smartBookGroup", "smartBookRetry", "smartBookErrorCodes"):
        opt.pop(stale, None)

    # Inject both SB configuration and SB groups into opt at create time.
    if sb_config_data is not None and sb_group_data is not None:
        opt["smartBooking"] = {
            "configuration": sb_config_data,
            "groups": [sb_group_data],
            "isEnabled": sb_enabled,
        }
    else:
        # SB is OFF for this scenario. The opt block above is deep-copied from the
        # shared template apiKey, which on stg carries a fully enabled
        # opt.smartBooking (isEnabled=true + the standing Expedia/NetSupplier/HBS
        # groups). Writing that through unchanged produces a "non-SB" scenario
        # whose apiKey silently books via SmartBooking. Neutralize the inherited
        # block instead of trusting whatever state the template happens to be in.
        _disable_inherited_smart_booking(opt)

    return {
        "name": api_key,
        "uid": api_key,
        "apikey": api_key,
        "nodeId": node_id,
        "contracts": contract_ids,
        # Fixed fields required for SB test scenarios
        "countryCode": "+971",
        "currency": "AFN",
        "locale": "EN",
        "pos": "AE",
        "platform": "all",
        "markup": "00",
        "opt": opt,
    }
