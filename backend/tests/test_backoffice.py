from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.backoffice import BackofficeClient, BackofficeError


@pytest.mark.asyncio
async def test_create_contract_success():
    response = MagicMock(status_code=201)
    response.json.return_value = {"_id": "contract-123"}
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)

    backoffice = BackofficeClient(client=client)
    backoffice._token = "token"
    backoffice.settings.tenant_id = "tenant-1"

    contract_id = await backoffice.create_contract({"uid": "smf-test"})
    assert contract_id == "contract-123"


@pytest.mark.asyncio
async def test_create_contract_failure_raises():
    response = MagicMock(status_code=400, text="bad request")
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)

    backoffice = BackofficeClient(client=client)
    backoffice._token = "token"

    with pytest.raises(BackofficeError):
        await backoffice.create_contract({"uid": "smf-test"})
