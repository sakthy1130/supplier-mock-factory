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
