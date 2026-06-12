import json

import httpx
import pytest

from app.integrations.business_rules import (
    DYNAMIC_MARKUP_RULE_ID,
    STATIC_MARKUP_RULE_ID,
    CrawlaBusinessRulesProvisioner,
    BusinessRulesClient,
)


@pytest.mark.asyncio
async def test_crawla_br_provision_creates_assignments_conditions_and_refresh(monkeypatch):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content))
        if request.url.path.endswith(f"/v1/apikeys/create-assign/rule/{STATIC_MARKUP_RULE_ID}"):
            return httpx.Response(200, json={"id": 301})
        if request.url.path.endswith(f"/v1/apikeys/create-assign/rule/{DYNAMIC_MARKUP_RULE_ID}"):
            return httpx.Response(200, json={"id": 401})
        if request.url.path.endswith("/rulevaluemappings"):
            body = json.loads(request.content.decode())
            condition_id = 901 if body["ruleId"] == STATIC_MARKUP_RULE_ID else 902
            return httpx.Response(201, json={"id": condition_id})
        if request.url.path.endswith("/refresh"):
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://br.test") as http_client:
        client = BusinessRulesClient(http_client)
        monkeypatch.setattr(client, "base_url", "http://br.test")
        setup = await CrawlaBusinessRulesProvisioner(client).provision("smf-crawla-test")

    assert setup["status"] == "SUCCESS"
    assert setup["rules"]["3"]["rule_config_id"] == "301"
    assert setup["rules"]["3"]["condition_id"] == "901"
    assert setup["rules"]["4"]["rule_config_id"] == "401"
    assert setup["rules"]["4"]["condition_id"] == "902"
    assert ("DELETE", "/refresh", b"") in calls


@pytest.mark.asyncio
async def test_crawla_br_cleanup_deletes_conditions_assignments_and_refresh(monkeypatch):
    calls = []
    setup = {
        "api_key": "smf-crawla-test",
        "rules": {
            "3": {"rule_config_id": "301", "condition_id": "901"},
            "4": {"rule_config_id": "401", "condition_id": "902"},
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(204 if request.method == "DELETE" else 200, json={"ruleConfigs": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://br.test") as http_client:
        client = BusinessRulesClient(http_client)
        monkeypatch.setattr(client, "base_url", "http://br.test")
        result = await CrawlaBusinessRulesProvisioner(client).cleanup(setup, "smf-crawla-test")

    assert result["status"] == "SUCCESS"
    assert ("DELETE", "/v1/rulevaluemappings/901") in calls
    assert ("DELETE", "/v1/rulevaluemappings/902") in calls
    assert ("DELETE", "/v1/ruleconfigs/301") in calls
    assert ("DELETE", "/v1/ruleconfigs/401") in calls
    assert ("DELETE", "/refresh") in calls
