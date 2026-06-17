"""Backoffice contract + apiKey node APIs. Port from ContractsSupplier."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class BackofficeError(RuntimeError):
    pass


class BackofficeClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.backoffice_url.rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._token: str | None = self.settings.backoffice_token or None

    async def __aenter__(self) -> "BackofficeClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
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
            self._client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True
        return self._client

    async def auth_headers(self) -> dict[str, str]:
        token = await self.ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.settings.tenant_id:
            headers["x-tenant"] = self.settings.tenant_id
        return headers

    async def ensure_token(self) -> str:
        if self._token:
            return self._token
        if not self.settings.backoffice_username or not self.settings.backoffice_password:
            raise BackofficeError("Backoffice credentials not configured")
        client = self._get_client()
        response = await client.post(
            f"{self.base_url}/api/account/user/login?src=qa_automation",
            json={
                "email": self.settings.backoffice_username,
                "password": self.settings.backoffice_password,
            },
            headers={"x-user-agent": "qa_automation", "Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise BackofficeError(f"Backoffice login failed status={response.status_code}")
        token = response.json().get("token")
        if not token:
            raise BackofficeError("Backoffice login response missing token")
        self._token = token
        return token

    async def get_contract(self, contract_id: str) -> dict[str, Any]:
        client = self._get_client()
        response = await client.get(
            f"{self.base_url}/api/contract/{contract_id}",
            headers=await self.auth_headers(),
        )
        if response.status_code != 200:
            raise BackofficeError(f"Get contract failed status={response.status_code}")
        return response.json()

    async def create_contract(self, body: dict[str, Any]) -> str:
        client = self._get_client()
        response = await client.post(
            f"{self.base_url}/api/contract",
            json=body,
            headers=await self.auth_headers(),
        )
        if response.status_code not in (200, 201):
            raise BackofficeError(f"Create contract failed status={response.status_code} body={response.text}")
        data = response.json()
        contract_id = data.get("_id") or data.get("id")
        if not contract_id:
            raise BackofficeError("Create contract response missing _id")
        return str(contract_id)

    async def update_contract(self, contract_id: str, body: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        response = await client.put(
            f"{self.base_url}/api/contract/{contract_id}",
            json=body,
            headers=await self.auth_headers(),
        )
        if response.status_code != 200:
            raise BackofficeError(f"Update contract failed status={response.status_code}")
        return response.json()

    async def find_api_key_by_uid(self, uid: str) -> dict[str, Any] | None:
        client = self._get_client()
        response = await client.get(
            f"{self.base_url}/api/node/user/filter",
            params={"query": uid},
            headers=await self.auth_headers(),
        )
        if response.status_code != 200:
            raise BackofficeError(f"ApiKey filter failed status={response.status_code}")
        data = response.json()
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            items = data.get("data") or data.get("items") or []
            if items:
                return items[0]
        return None

    async def create_api_key(self, body: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        url = f"{self.base_url}/api/node/user"
        logger.info("[BackofficeClient] POST %s  body=%s", url, body)
        response = await client.post(url, json=body, headers=await self.auth_headers())
        logger.info(
            "[BackofficeClient] POST %s  status=%d  response=%s",
            url, response.status_code, response.text,
        )
        if response.status_code not in (200, 201):
            raise BackofficeError(f"Create apiKey failed status={response.status_code} body={response.text}")
        return response.json()

    async def update_api_key(self, api_key_id: str, node_id: str, body: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        url = f"{self.base_url}/api/node/user/{api_key_id}/{node_id}"
        logger.info("[BackofficeClient] PUT %s  body=%s", url, body)
        response = await client.put(url, json=body, headers=await self.auth_headers())
        logger.info(
            "[BackofficeClient] PUT %s  status=%d  response=%s",
            url, response.status_code, response.text,
        )
        if response.status_code != 200:
            raise BackofficeError(f"Update apiKey failed status={response.status_code} body={response.text}")
        return response.json()

    async def get_api_key_config(self, api_key_id: str, node_id: str) -> dict[str, Any]:
        client = self._get_client()
        response = await client.get(
            f"{self.base_url}/api/node/user/{api_key_id}/{node_id}",
            headers=await self.auth_headers(),
        )
        if response.status_code != 200:
            raise BackofficeError(f"Get apiKey config failed status={response.status_code}")
        return response.json()

    async def delete_contract(self, contract_id: str) -> None:
        client = self._get_client()
        response = await client.delete(
            f"{self.base_url}/api/contract/{contract_id}",
            headers=await self.auth_headers(),
        )
        if response.status_code not in (200, 204, 404):
            raise BackofficeError(
                f"Delete contract failed status={response.status_code} body={response.text}"
            )

    async def delete_api_key(self, api_key_id: str) -> None:
        tenant_id = self.settings.tenant_id
        if not tenant_id:
            raise BackofficeError("tenant_id not configured — cannot delete apiKey")
        client = self._get_client()
        response = await client.delete(
            f"{self.base_url}/api/node/user/{api_key_id}/{tenant_id}",
            headers=await self.auth_headers(),
        )
        if response.status_code not in (200, 204, 404):
            raise BackofficeError(
                f"Delete apiKey failed status={response.status_code} body={response.text}"
            )
