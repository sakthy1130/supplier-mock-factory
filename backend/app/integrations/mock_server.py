"""MockServer client. Port from CreateExpectationWrapper / DeleteExpectationWrapper."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.core.namespace import expectation_ids_for_namespace

logger = logging.getLogger(__name__)


class MockServerError(RuntimeError):
    pass


class MockServerClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        base = self.settings.mock_server_url.rstrip("/")
        self.expectation_url = f"{base}/mockserver/expectation"
        self.clear_url = f"{base}/mockserver/clear"
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "MockServerClient":
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

    async def register_expectation(self, expectation: dict) -> None:
        """PUT /mockserver/expectation — expects HTTP 201."""
        client = self._get_client()
        response = await client.put(
            self.expectation_url,
            json=expectation,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if response.status_code != 201:
            raise MockServerError(
                f"MockServer register failed status={response.status_code} body={response.text}"
            )

    async def register_expectations(self, expectations: list[dict]) -> int:
        for expectation in expectations:
            await self.register_expectation(expectation)
        return len(expectations)

    async def delete_expectations(self, matcher: dict | None = None) -> None:
        """PUT /mockserver/clear?type=expectations — expects HTTP 200."""
        client = self._get_client()
        response = await client.put(
            self.clear_url,
            params={"type": "expectations"},
            json=matcher or {},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise MockServerError(
                f"MockServer delete failed status={response.status_code} body={response.text}"
            )

    async def delete_all_expectations(self) -> None:
        """Clear every expectation on MockServer."""
        await self.delete_expectations({})

    async def delete_expectations_tolerant(self, matcher: dict) -> None:
        """Clear expectations; ignore 400 when matcher finds nothing."""
        client = self._get_client()
        response = await client.put(
            self.clear_url,
            params={"type": "expectations"},
            json=matcher,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if response.status_code == 400:
            logger.debug("MockServer clear no match matcher=%s", matcher)
            return
        if response.status_code != 200:
            raise MockServerError(
                f"MockServer delete failed status={response.status_code} body={response.text}"
            )

    async def delete_by_namespace(
        self,
        namespace: str,
        suppliers: list[str] | None = None,
    ) -> None:
        for expectation_id in expectation_ids_for_namespace(namespace, suppliers):
            await self.delete_expectations_tolerant({"id": expectation_id})
