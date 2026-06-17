"""Provision and teardown Smart Booking configuration and groups via Backoffice dynamic-forms API."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.integrations.backoffice import BackofficeClient, BackofficeError
from app.integrations.config_manager import ConfigManagerClient
from app.models.scenario import SBScenarioConfig

logger = logging.getLogger(__name__)

SB_CONFIG_API_PATH = "/api/dynamic-forms/smart_booking"
SB_GROUP_API_PATH = "/api/dynamic-forms/smart_booking_group"


class SBGroupProvisioner:
    """Creates, assigns, and deletes SB configuration + groups for test scenarios."""

    def __init__(
        self,
        backoffice: BackofficeClient | None = None,
        config_manager: ConfigManagerClient | None = None,
    ) -> None:
        self.backoffice = backoffice or BackofficeClient()
        self.config_manager = config_manager or ConfigManagerClient(self.backoffice)

    async def create_sb_config(
        self,
        sb_config: SBScenarioConfig,
        namespace: str,
    ) -> dict[str, Any]:
        """Create SB configuration entity. Returns {_id, name, created_at}."""
        async with self.backoffice:
            result = await self._create_sb_config_entity(sb_config, namespace)
            logger.info(
                "SB config created: _id=%s name=%s namespace=%s",
                result["_id"], result["name"], namespace,
            )
            return result

    async def create_group(
        self,
        namespace: str,
        contract_ids: list[str],
    ) -> dict[str, Any]:
        """Create SB group entity. Returns {_id, name, created_at}. Call AFTER contracts are created."""
        async with self.backoffice:
            result = await self._create_sb_group(namespace, contract_ids)
            logger.info(
                "SB group created: _id=%s name=%s namespace=%s",
                result["_id"], result["name"], namespace,
            )
            return result

    async def assign_to_api_key(
        self,
        api_key_id: str,
        api_key: str,
        node_id: str,
        sb_config_data: dict[str, Any],
        sb_group_data: dict[str, Any],
        sb_config: SBScenarioConfig,
        prov_log: list[str] | None = None,
    ) -> None:
        """Assign SB config + group to apiKey as opt.smartBooking, then clear cache."""
        def _plog(msg: str) -> None:
            logger.info(msg)
            if prov_log is not None:
                prov_log.append(msg)

        async with self.backoffice:
            await self._assign_smart_booking_to_api_key(
                api_key_id=api_key_id,
                node_id=node_id,
                sb_config_data=sb_config_data,
                sb_group_data=sb_group_data,
                sb_config=sb_config,
            )
            _plog(
                f"[sb assign] PUT /api/node/user/{api_key_id}/{node_id}  "
                f"opt.smartBooking.configuration._id={sb_config_data['_id']} "
                f"opt.smartBooking.groups[0]._id={sb_group_data['_id']} "
                f"isEnabled={sb_config.enable_profitable_sb} → 200 OK"
            )
            await self.config_manager.clear_api_key_cache(api_key)
            _plog(f"[cache clear after SB] POST /api/v1/cache/config/clear/{api_key} → 200 OK")

    async def teardown(
        self,
        group_id: str,
        api_key_id: str,
        node_id: str,
        sb_config_id: str | None = None,
    ) -> None:
        """Disable SB on apiKey, delete group and config. Best-effort."""
        async with self.backoffice:
            try:
                await self._disable_sb_on_api_key(api_key_id, node_id)
                logger.info("SB disabled on apiKey: api_key_id=%s", api_key_id)
            except Exception as exc:
                logger.error(
                    "Failed to disable SB on apiKey api_key_id=%s: %s", api_key_id, exc
                )

            try:
                await self._delete_sb_group(group_id)
                logger.info("SB group deleted: group_id=%s", group_id)
            except Exception as exc:
                logger.error("Failed to delete SB group group_id=%s: %s", group_id, exc)

            if sb_config_id:
                try:
                    await self._delete_sb_config(sb_config_id)
                    logger.info("SB config deleted: config_id=%s", sb_config_id)
                except Exception as exc:
                    logger.error("Failed to delete SB config config_id=%s: %s", sb_config_id, exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _create_sb_config_entity(
        self, sb_config: SBScenarioConfig, namespace: str
    ) -> dict[str, Any]:
        config_name = f"smf-sb-{namespace}"
        gc = sb_config.group_configuration
        body: dict[str, Any] = {
            "name": config_name,
            "label": config_name,
            "enableNewSession": sb_config.enable_new_session,
            "isActive": True,
            "autoId": "",
            "uid": config_name,
            "groupConfiguration": {
                "survey1": {
                    "class": gc.survey1_class,
                    "type": gc.survey1_type,
                    "view": gc.survey1_view,
                    "bedding": gc.survey1_bedding,
                },
                "board": gc.board,
                "cancellationPolicy": gc.cancellation_policy,
            },
            "price": {
                "priceMarginPercentage": sb_config.price_margin_percentage,
                "ignoreDeltaProfitAmount": sb_config.forfeit_amount,
            },
            "opt": {
                "fetchCancellationPolicyForExcludedPackages": sb_config.fetch_cancellation_policy_for_excluded,
                "considerSameVatGroupsForCountries": sb_config.consider_same_vat_groups,
                "considerOriginalPackage": sb_config.consider_original_package,
            },
            "submit": True,
        }
        client = self.backoffice._get_client()
        url = f"{self.backoffice.base_url}{SB_CONFIG_API_PATH}"
        logger.info("[SB config CREATE] POST %s  body=%s", url, body)
        response = await client.post(
            url,
            json=body,
            headers=await self.backoffice.auth_headers(),
        )
        logger.info(
            "[SB config CREATE] status=%d  response=%s", response.status_code, response.text
        )
        if response.status_code not in (200, 201):
            raise BackofficeError(
                f"Create SB config failed status={response.status_code} body={response.text}"
            )
        data = response.json()
        config_id = data.get("_id") or data.get("id")
        if not config_id:
            raise BackofficeError("Create SB config response missing _id")
        return {
            "_id": str(config_id),
            "name": str(data.get("name", config_name)),
            "created_at": data.get("created_at") or data.get("createdAt") or 0,
        }

    async def _create_sb_group(
        self, namespace: str, contract_ids: list[str]
    ) -> dict[str, Any]:
        group_name = f"smf-sb-{namespace}"
        body = _build_sb_group_body(group_name, contract_ids)
        client = self.backoffice._get_client()
        url = f"{self.backoffice.base_url}{SB_GROUP_API_PATH}"
        logger.info("[SB group CREATE] POST %s  body=%s", url, body)
        response = await client.post(
            url,
            json=body,
            headers=await self.backoffice.auth_headers(),
        )
        logger.info(
            "[SB group CREATE] status=%d  response=%s", response.status_code, response.text
        )
        if response.status_code not in (200, 201):
            raise BackofficeError(
                f"Create SB group failed status={response.status_code} body={response.text}"
            )
        data = response.json()
        group_id = data.get("_id") or data.get("id")
        if not group_id:
            raise BackofficeError("Create SB group response missing _id")
        return {
            "_id": str(group_id),
            "name": str(data.get("name", group_name)),
            "created_at": data.get("created_at") or data.get("createdAt") or 0,
        }

    async def _assign_smart_booking_to_api_key(
        self,
        api_key_id: str,
        node_id: str,
        sb_config_data: dict[str, Any],
        sb_group_data: dict[str, Any],
        sb_config: SBScenarioConfig,
    ) -> None:
        """Read current apiKey config, set opt.smartBooking nested structure, write back."""
        config = await self.backoffice.get_api_key_config(api_key_id, node_id)
        opt = config.get("opt") or {}

        # Remove stale flat SB fields that may have been set by old code
        for stale in ("smartBook", "smartBookGroup", "smartBookRetry", "smartBookErrorCodes"):
            opt.pop(stale, None)

        # Set the correct nested smartBooking structure
        opt["smartBooking"] = {
            "configuration": sb_config_data,
            "groups": [sb_group_data],
            "isEnabled": sb_config.enable_profitable_sb,
        }

        if sb_config.winning_packages_enabled:
            opt["winningPackagesEnabled"] = True

        if sb_config.enable_retry_sb:
            opt["smartBookRetry"] = True
        if sb_config.retry_error_codes:
            opt["smartBookErrorCodes"] = sb_config.retry_error_codes

        config["opt"] = opt
        # Log the FULL update body so opt.smartBooking is visible for debugging
        logger.info(
            "[SB assign] PUT /api/node/user/%s/%s  FULL_BODY=%s",
            api_key_id, node_id, json.dumps(config, default=str),
        )
        await self.backoffice.update_api_key(api_key_id, node_id, config)

    async def _disable_sb_on_api_key(self, api_key_id: str, node_id: str) -> None:
        """Read current apiKey config, remove all SB fields, write back."""
        config = await self.backoffice.get_api_key_config(api_key_id, node_id)
        opt = config.get("opt") or {}
        for field in ("smartBooking", "smartBook", "smartBookGroup", "smartBookRetry",
                      "smartBookErrorCodes", "winningPackagesEnabled"):
            opt.pop(field, None)
        config["opt"] = opt
        await self.backoffice.update_api_key(api_key_id, node_id, config)

    async def _delete_sb_group(self, group_id: str) -> None:
        client = self.backoffice._get_client()
        response = await client.delete(
            f"{self.backoffice.base_url}{SB_GROUP_API_PATH}/{group_id}",
            headers=await self.backoffice.auth_headers(),
        )
        if response.status_code not in (200, 204, 404):
            raise BackofficeError(
                f"Delete SB group failed status={response.status_code} body={response.text}"
            )

    async def _delete_sb_config(self, config_id: str) -> None:
        client = self.backoffice._get_client()
        response = await client.delete(
            f"{self.backoffice.base_url}{SB_CONFIG_API_PATH}/{config_id}",
            headers=await self.backoffice.auth_headers(),
        )
        if response.status_code not in (200, 204, 404):
            raise BackofficeError(
                f"Delete SB config failed status={response.status_code} body={response.text}"
            )


def _build_sb_group_body(group_name: str, contract_ids: list[str]) -> dict[str, Any]:
    """Build POST /api/dynamic-forms/smart_booking_group body."""
    return {
        "name": group_name,
        "isActive": True,
        "contracts": contract_ids,
        "submit": True,
    }
