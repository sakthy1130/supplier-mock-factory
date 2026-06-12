"""Create new apiKey per scenario and attach contracts."""

from __future__ import annotations

import copy
from typing import Any

from app.config import get_settings
from app.integrations.backoffice import BackofficeClient, BackofficeError
from app.integrations.config_manager import ConfigManagerClient

DEFAULT_API_KEY_TEMPLATE = "Fayrouztest"


class ApiKeyProvisioner:
    def __init__(
        self,
        backoffice: BackofficeClient | None = None,
        config_manager: ConfigManagerClient | None = None,
    ) -> None:
        self.backoffice = backoffice or BackofficeClient()
        self.config_manager = config_manager or ConfigManagerClient(self.backoffice)
        self.settings = get_settings()

    async def create_api_key(self, contract_ids: dict[str, str], namespace: str) -> tuple[str, str]:
        api_key = _api_key_value(namespace)
        node_id = self.settings.tenant_id
        if not node_id:
            raise ValueError("TENANT_ID is required to provision apiKey")

        async with self.backoffice:
            template_name = self.settings.api_key_template_uid or DEFAULT_API_KEY_TEMPLATE
            summary = await self.backoffice.find_api_key_by_uid(template_name)
            if not summary or not summary.get("_id"):
                raise BackofficeError(f"ApiKey template not found: {template_name}")

            template = await self.backoffice.get_api_key_config(str(summary["_id"]), node_id)
            body = _clone_api_key_template(template, api_key, node_id)

            created = await self.backoffice.create_api_key(body)
            api_key_id = str(created.get("_id") or created.get("id") or "")
            api_key = str(created.get("apikey") or created.get("uid") or api_key)
            if not api_key_id:
                raise ValueError("Create apiKey response missing _id")

            config = await self.backoffice.get_api_key_config(api_key_id, node_id)
            config["contracts"] = _ordered_contract_ids(contract_ids)
            await self.backoffice.update_api_key(api_key_id, node_id, config)
            await self.config_manager.clear_api_key_cache(api_key)
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


def _clone_api_key_template(template: dict[str, Any], api_key: str, node_id: str) -> dict[str, Any]:
    body = copy.deepcopy(template)
    for key in ("_id", "id", "createdAt", "updatedAt", "created_at", "update_at", "__v"):
        body.pop(key, None)
    body["apikey"] = api_key
    body["uid"] = api_key
    body["name"] = api_key
    body["nodeId"] = node_id
    body["contracts"] = []
    return body
