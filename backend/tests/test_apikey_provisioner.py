from unittest.mock import AsyncMock

import pytest

from app.core.apikey_provisioner import ApiKeyProvisioner


@pytest.mark.asyncio
async def test_create_api_key_attaches_contracts_and_clears_cache():
    backoffice = AsyncMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=None)
    backoffice.find_api_key_by_uid = AsyncMock(return_value={"_id": "template-id", "apikey": "Fayrouztest"})
    backoffice.get_api_key_config = AsyncMock(
        side_effect=[
            {"_id": "template-id", "uid": "Fayrouztest", "apikey": "Fayrouztest", "opt": {}},
            {"contracts": [], "currency": "AED"},
        ]
    )
    backoffice.create_api_key = AsyncMock(
        return_value={"_id": "key-id-1", "uid": "smf-qa-p4-001", "apikey": "smf-qa-p4-001"}
    )
    backoffice.update_api_key = AsyncMock(return_value={"ok": True})

    config_manager = AsyncMock()
    config_manager.clear_api_key_cache = AsyncMock()

    provisioner = ApiKeyProvisioner(backoffice=backoffice, config_manager=config_manager)
    provisioner.settings.tenant_id = "tenant-1"

    api_key, api_key_id = await provisioner.create_api_key(
        {"HBS": "mongo-hbs", "EXP": "mongo-exp"},
        "qa-p4-001",
    )

    assert api_key == "smf-qa-p4-001"
    assert api_key_id == "key-id-1"
    update_body = backoffice.update_api_key.await_args.args[2]
    assert update_body["contracts"] == ["mongo-hbs", "mongo-exp"]
    config_manager.clear_api_key_cache.assert_awaited_once_with("smf-qa-p4-001")
