"""Business Rules service client for Crawla scenario provisioning."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
BR_CHILD_CONDITIONS_PATH = REPO_ROOT / "field-maps" / "br_child_conditions.json"
BR_CONTRACT_CONDITIONS_PATH = REPO_ROOT / "field-maps" / "br_contract_conditions.json"


STATIC_MARKUP_RULE_ID = 3
DYNAMIC_MARKUP_RULE_ID = 4
STATIC_MARKUP_PARENT_CONDITION_ID = 178
DYNAMIC_MARKUP_PARENT_CONDITION_ID = 176
API_KEY_INPUT_DETAIL_ID = 26
STATIC_MARKUP_OUTPUT_DETAIL_ID = 4
DYNAMIC_MARKUP_OUTPUT_DETAIL_ID = 8


class BusinessRulesError(RuntimeError):
    pass


class BusinessRulesClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.business_rules_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "BusinessRulesClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "userId": "22",
        }
        if self.settings.tenant_id:
            headers["X-Tenant"] = self.settings.tenant_id
        return headers

    async def add_and_assign_api_key(self, rule_id: int, api_key: str) -> dict[str, Any]:
        response = await self._get_client().post(
            f"{self.base_url}/v1/apikeys/create-assign/rule/{rule_id}",
            json={"name": api_key, "description": api_key},
            headers=self._headers(),
        )
        if response.status_code not in (200, 201):
            raise BusinessRulesError(
                f"BR add/assign apiKey failed ruleId={rule_id} status={response.status_code} body={response.text}"
            )
        return _json_or_empty(response)

    async def create_condition(
        self,
        *,
        rule_id: int,
        parent_condition_id: int,
        output_detail_id: int,
        api_key: str,
        output_value: str,
    ) -> dict[str, Any]:
        body = {
            "ruleId": rule_id,
            "description": "APIKey Included",
            "parentRuleValueMappingId": parent_condition_id,
            "inputDetailId": API_KEY_INPUT_DETAIL_ID,
            "outputDetailId": output_detail_id,
            "inputValue": api_key,
            "inputValueListId": None,
            "outputValue": output_value,
            "overwrite": True,
            "executionOrder": 150,
        }
        response = await self._get_client().post(
            f"{self.base_url}/rulevaluemappings",
            json=body,
            headers=self._headers(),
        )
        if response.status_code not in (200, 201):
            raise BusinessRulesError(
                f"BR create condition failed ruleId={rule_id} status={response.status_code} body={response.text}"
            )
        return _json_or_empty(response)

    async def create_condition_raw(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST an arbitrary rule-value-mapping body verbatim (e.g. per-template child
        BR conditions, whose field shape doesn't match create_condition's fixed signature)."""
        response = await self._get_client().post(
            f"{self.base_url}/rulevaluemappings",
            json=body,
            headers=self._headers(),
        )
        if response.status_code not in (200, 201):
            raise BusinessRulesError(
                f"BR create condition (raw) failed status={response.status_code} body={response.text}"
            )
        return _json_or_empty(response)

    async def get_rule_configs(self, rule_id: int) -> list[dict[str, Any]]:
        response = await self._get_client().get(
            f"{self.base_url}/v1/ruleconfigs/rule/{rule_id}",
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise BusinessRulesError(
                f"BR get rule configs failed ruleId={rule_id} status={response.status_code} body={response.text}"
            )
        data = _json_or_empty(response)
        rule_configs = data.get("ruleConfigs")
        return rule_configs if isinstance(rule_configs, list) else []

    async def delete_rule_config(self, rule_config_id: str) -> None:
        response = await self._get_client().delete(
            f"{self.base_url}/v1/ruleconfigs/{rule_config_id}",
            headers=self._headers(),
        )
        if response.status_code not in (200, 204, 404):
            raise BusinessRulesError(
                f"BR delete rule config failed id={rule_config_id} status={response.status_code} body={response.text}"
            )

    async def delete_condition(self, condition_id: str) -> None:
        response = await self._get_client().delete(
            f"{self.base_url}/v1/rulevaluemappings/{condition_id}",
            headers=self._headers(),
        )
        if response.status_code not in (200, 204, 404):
            raise BusinessRulesError(
                f"BR delete condition failed id={condition_id} status={response.status_code} body={response.text}"
            )

    async def refresh(self) -> None:
        response = await self._get_client().delete(
            f"{self.base_url}/refresh",
            headers=self._headers(),
        )
        if response.status_code not in (200, 204):
            raise BusinessRulesError(
                f"BR refresh failed status={response.status_code} body={response.text}"
            )


class CrawlaBusinessRulesProvisioner:
    def __init__(self, client: BusinessRulesClient | None = None) -> None:
        self.client = client or BusinessRulesClient()

    async def provision(self, api_key: str, template_id: str | None = None) -> dict[str, Any]:
        setup: dict[str, Any] = {
            "enabled": True,
            "status": "SUCCESS",
            "api_key": api_key,
            "rules": {},
            "errors": [],
        }
        async with self.client:
            await self._run_step(setup, "assign_static", self._assign_rule, STATIC_MARKUP_RULE_ID, api_key)
            await self._run_step(setup, "assign_dynamic", self._assign_rule, DYNAMIC_MARKUP_RULE_ID, api_key)
            await self._run_step(
                setup,
                "condition_static",
                self._create_condition,
                STATIC_MARKUP_RULE_ID,
                STATIC_MARKUP_PARENT_CONDITION_ID,
                STATIC_MARKUP_OUTPUT_DETAIL_ID,
                api_key,
                "10%",
            )
            await self._run_step(
                setup,
                "condition_dynamic",
                self._create_condition,
                DYNAMIC_MARKUP_RULE_ID,
                DYNAMIC_MARKUP_PARENT_CONDITION_ID,
                DYNAMIC_MARKUP_OUTPUT_DETAIL_ID,
                api_key,
                "15%-25%",
            )
            if template_id:
                dynamic_parent_id = _rule_data(setup, DYNAMIC_MARKUP_RULE_ID).get("condition_id")
                if dynamic_parent_id:
                    await self._run_step(
                        setup,
                        "template_child_conditions",
                        self._create_template_child_conditions,
                        template_id,
                        dynamic_parent_id,
                    )
                else:
                    setup["errors"].append({
                        "step": "template_child_conditions",
                        "message": "dynamic parent condition id missing — cannot create child condition",
                    })
            await self._run_step(setup, "refresh", self.client.refresh)
        if setup["errors"]:
            setup["status"] = "FAILED"
            setup["warning"] = "BR setup failed"
        return setup

    async def _create_template_child_conditions(
        self,
        template_id: str,
        parent_condition_id: str,
    ) -> dict[str, Any]:
        """Create per-template child BR conditions under the DynamicMarkup rule,
        using THIS scenario's own freshly-created dynamic-markup condition as the
        parent (parentRuleValueMappingId is always the live id, never a stored one)."""
        payloads = _load_template_child_conditions().get(self.client.settings.env, {}).get(template_id, [])
        created: list[dict[str, Any]] = []
        for payload in payloads:
            body = {**payload, "parentRuleValueMappingId": int(parent_condition_id)}
            response = await self.client.create_condition_raw(body)
            child_id = _extract_id(response)
            if child_id:
                created.append(child_id)
        return {"rule_id": DYNAMIC_MARKUP_RULE_ID, "template_child_condition_ids": created}

    async def provision_for_contracts(self, contracts: list[dict[str, Any]]) -> dict[str, Any]:
        """Assign CONTRACTS (not an apiKey) to the markup rules — the contract_br depth.

        Config-driven via field-maps/br_contract_conditions.json because SMF's BR
        integration is otherwise entirely apiKey-shaped (inputDetailId 26) and the
        contract input id is not known yet. With no config for this env the step
        reports NOT_CONFIGURED and records an error, rather than reporting success
        for work it did not do.

        `contracts` is a list of {"instance_key", "uid", "id"} for the scenario's
        created contracts.
        """
        setup: dict[str, Any] = {
            "enabled": True,
            "status": "SUCCESS",
            "mode": "contract",
            "contracts": [c.get("uid") or c.get("id") for c in contracts],
            "rules": {},
            "contract_condition_ids": [],
            "errors": [],
        }
        config = _load_contract_conditions().get(self.client.settings.env) or {}
        payloads = config.get("conditions") or []
        if not payloads:
            setup["status"] = "NOT_CONFIGURED"
            setup["warning"] = (
                "No contract BR conditions configured for env="
                f"{self.client.settings.env}. Add them to field-maps/br_contract_conditions.json "
                "(the contract inputDetailId is still unknown); mocks and contracts were created."
            )
            logger.warning(setup["warning"])
            setup["errors"].append({"step": "contract_conditions", "message": "not configured"})
            return setup

        value_field = config.get("contract_value_field") or "autoId"
        # The real condition is "contractId IN <comma-separated list>", so by default
        # every contract goes into ONE condition. per_contract is there for a
        # single-value operator (EQUALS), which would need one condition each.
        value_mode = config.get("value_mode") or "join"
        separator = config.get("value_separator") or ","

        values: list[str] = []
        for contract in contracts:
            value = contract.get(value_field)
            if value in (None, ""):
                setup["errors"].append({
                    "step": "contract_conditions",
                    "message": (
                        f"contract {contract.get('instance_key')} has no '{value_field}' — "
                        f"cannot build the BR condition inputValue"
                    ),
                })
                continue
            values.append(str(value))

        if not values:
            setup["status"] = "FAILED"
            setup["warning"] = f"No contract '{value_field}' values available for the BR condition"
            return setup

        input_values = [separator.join(values)] if value_mode == "join" else values
        setup["input_values"] = input_values
        async with self.client:
            for input_value in input_values:
                for payload in payloads:
                    # Deliberately not _run_step: it merges results into
                    # setup["rules"][rule_id], so several conditions on one rule would
                    # overwrite each other's condition_id and teardown would leak them.
                    try:
                        created = await self._create_contract_condition(payload, input_value)
                        if created.get("condition_id"):
                            setup["contract_condition_ids"].append(created["condition_id"])
                    except Exception as exc:  # noqa: BLE001 - BR setup is non-blocking by design
                        logger.exception("BR contract condition failed value=%s", input_value)
                        setup["errors"].append({"step": "contract_condition", "message": str(exc)})
            await self._run_step(setup, "refresh", self.client.refresh)
        if setup["errors"]:
            setup["status"] = "FAILED"
            setup["warning"] = "BR contract setup failed"
        return setup

    async def _create_contract_condition(
        self,
        payload: dict[str, Any],
        input_value: str,
    ) -> dict[str, Any]:
        body = {**payload, "inputValue": input_value}
        response = await self.client.create_condition_raw(body)
        condition_id = _extract_id(response)
        return {
            "rule_id": body.get("ruleId"),
            "condition_id": condition_id,
            "input_value": input_value,
        }

    async def cleanup(self, setup: dict[str, Any] | None, api_key: str | None) -> dict[str, Any]:
        if not setup and not api_key:
            return {"enabled": False, "status": "SKIPPED", "errors": []}
        api_key = api_key or str((setup or {}).get("api_key") or "")
        result: dict[str, Any] = {"enabled": True, "status": "SUCCESS", "errors": []}

        # contract_br scenarios have no apiKey rule-configs to unpick — just the
        # contract conditions this scenario created.
        contract_condition_ids = list((setup or {}).get("contract_condition_ids") or [])
        if contract_condition_ids:
            async with self.client:
                for condition_id in contract_condition_ids:
                    await self._cleanup_step(
                        result, "delete_contract_condition", self.client.delete_condition, str(condition_id)
                    )
                await self._cleanup_step(result, "refresh", self.client.refresh)
            if result["errors"]:
                result["status"] = "FAILED"
                result["warning"] = "BR contract cleanup failed"
            if not api_key:
                return result

        async with self.client:
            # Child conditions reference the parent via parentRuleValueMappingId — the
            # BR service won't let a parent be deleted while a child still points at
            # it, so children must always be deleted first.
            for rule_id in (STATIC_MARKUP_RULE_ID, DYNAMIC_MARKUP_RULE_ID):
                rule_data = _rule_data(setup, rule_id)
                for child_id in rule_data.get("template_child_condition_ids") or []:
                    await self._cleanup_step(
                        result, "delete_template_child_condition", self.client.delete_condition, str(child_id)
                    )

            for rule_id in (STATIC_MARKUP_RULE_ID, DYNAMIC_MARKUP_RULE_ID):
                rule_data = _rule_data(setup, rule_id)
                condition_id = rule_data.get("condition_id")
                if condition_id:
                    await self._cleanup_step(result, "delete_condition", self.client.delete_condition, str(condition_id))

            for rule_id in (STATIC_MARKUP_RULE_ID, DYNAMIC_MARKUP_RULE_ID):
                rule_data = _rule_data(setup, rule_id)
                stored_config_id = rule_data.get("rule_config_id")
                config_ids = [str(stored_config_id)] if stored_config_id else []
                config_ids.extend(await self._find_rule_config_ids(rule_id, api_key))
                for rule_config_id in dict.fromkeys(config_ids):
                    await self._cleanup_step(result, "delete_rule_config", self.client.delete_rule_config, rule_config_id)

            await self._cleanup_step(result, "refresh", self.client.refresh)
        if result["errors"]:
            result["status"] = "FAILED"
            result["warning"] = "BR cleanup failed"
        return result

    async def _assign_rule(self, rule_id: int, api_key: str) -> dict[str, Any]:
        response = await self.client.add_and_assign_api_key(rule_id, api_key)
        rule_config_id = _extract_id(response)
        if not rule_config_id:
            matches = await self._find_rule_config_ids(rule_id, api_key)
            rule_config_id = matches[0] if matches else None
        return {"rule_id": rule_id, "rule_config_id": rule_config_id, "assign_response": response}

    async def _create_condition(
        self,
        rule_id: int,
        parent_condition_id: int,
        output_detail_id: int,
        api_key: str,
        output_value: str,
    ) -> dict[str, Any]:
        response = await self.client.create_condition(
            rule_id=rule_id,
            parent_condition_id=parent_condition_id,
            output_detail_id=output_detail_id,
            api_key=api_key,
            output_value=output_value,
        )
        return {
            "rule_id": rule_id,
            "parent_condition_id": parent_condition_id,
            "condition_id": _extract_id(response),
            "output_value": output_value,
        }

    async def _find_rule_config_ids(self, rule_id: int, api_key: str) -> list[str]:
        if not api_key:
            return []
        configs = await self.client.get_rule_configs(rule_id)
        ids: list[str] = []
        for config in configs:
            configured_api_key = config.get("apiKey")
            if isinstance(configured_api_key, dict):
                name = str(configured_api_key.get("name") or configured_api_key.get("apikey") or "")
            else:
                name = str(config.get("apiKeyName") or config.get("apikey") or "")
            if name.lower() == api_key.lower():
                config_id = _extract_id(config)
                if config_id:
                    ids.append(config_id)
        return ids

    async def _run_step(self, setup: dict[str, Any], step: str, func: Any, *args: Any) -> None:
        try:
            data = await func(*args)
            if isinstance(data, dict) and "rule_id" in data:
                rule_key = str(data["rule_id"])
                setup["rules"].setdefault(rule_key, {}).update(
                    {key: value for key, value in data.items() if key != "rule_id" and value is not None}
                )
        except Exception as exc:  # noqa: BLE001 - non-blocking BR setup by design
            logger.exception("Crawla BR setup step failed step=%s", step)
            setup["errors"].append({"step": step, "message": str(exc)})

    async def _cleanup_step(self, result: dict[str, Any], step: str, func: Any, *args: Any) -> None:
        try:
            await func(*args)
        except Exception as exc:  # noqa: BLE001 - teardown must continue best-effort
            logger.exception("Crawla BR cleanup step failed step=%s", step)
            result["errors"].append({"step": step, "message": str(exc)})


def _load_template_child_conditions() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{env: {template_id: [condition_payload, ...]}} — read fresh each call, same
    no-caching style as scenario_engine's template loading, so edits to the JSON
    file take effect without a restart."""
    if not BR_CHILD_CONDITIONS_PATH.exists():
        return {}
    return json.loads(BR_CHILD_CONDITIONS_PATH.read_text(encoding="utf-8"))


def _load_contract_conditions() -> dict[str, dict[str, Any]]:
    """{env: {"contract_value_field": ..., "conditions": [...]}} — read fresh each call
    so filling in the real contract inputDetailId needs no restart."""
    if not BR_CONTRACT_CONDITIONS_PATH.exists():
        return {}
    data = json.loads(BR_CONTRACT_CONDITIONS_PATH.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def has_contract_br_conditions(env: str) -> bool:
    """Whether the contract_br depth can actually create BR conditions in this env."""
    return bool((_load_contract_conditions().get(env) or {}).get("conditions"))


def has_template_child_condition(template_id: str, env: str) -> bool:
    """Public helper for surfacing configured template ids to the UI (e.g. a badge
    on the template list), without exposing the raw condition payloads."""
    return bool(_load_template_child_conditions().get(env, {}).get(template_id))


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


def _extract_id(data: dict[str, Any]) -> str | None:
    for key in ("id", "_id", "ruleConfigId", "rule_config_id"):
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _rule_data(setup: dict[str, Any] | None, rule_id: int) -> dict[str, Any]:
    rules = (setup or {}).get("rules")
    if not isinstance(rules, dict):
        return {}
    data = rules.get(str(rule_id)) or rules.get(rule_id)
    return data if isinstance(data, dict) else {}
