"""Business Rules service client for Crawla scenario provisioning."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


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

    async def provision(self, api_key: str) -> dict[str, Any]:
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
            await self._run_step(setup, "refresh", self.client.refresh)
        if setup["errors"]:
            setup["status"] = "FAILED"
            setup["warning"] = "BR setup failed"
        return setup

    async def cleanup(self, setup: dict[str, Any] | None, api_key: str | None) -> dict[str, Any]:
        if not setup and not api_key:
            return {"enabled": False, "status": "SKIPPED", "errors": []}
        api_key = api_key or str((setup or {}).get("api_key") or "")
        result: dict[str, Any] = {"enabled": True, "status": "SUCCESS", "errors": []}
        async with self.client:
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
