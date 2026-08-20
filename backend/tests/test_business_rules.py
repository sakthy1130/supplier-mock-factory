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


@pytest.mark.asyncio
async def test_crawla_br_cleanup_deletes_template_child_condition_before_parent(monkeypatch):
    """The BR service rejects deleting a parent condition while a child still
    references it via parentRuleValueMappingId — child(ren) must be deleted first."""
    calls = []
    setup = {
        "api_key": "smf-crawla-test",
        "rules": {
            "3": {"rule_config_id": "301", "condition_id": "901"},
            "4": {
                "rule_config_id": "401",
                "condition_id": "902",
                "template_child_condition_ids": ["903"],
            },
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
    delete_calls = [path for method, path in calls if method == "DELETE" and "rulevaluemappings" in path]
    child_index = delete_calls.index("/v1/rulevaluemappings/903")
    parent_index = delete_calls.index("/v1/rulevaluemappings/902")
    assert child_index < parent_index, "child condition must be deleted before its parent"


@pytest.mark.asyncio
async def test_provision_creates_template_child_condition_with_dynamic_parent_id(monkeypatch):
    """parentRuleValueMappingId on the child condition must be THIS run's own
    dynamic-markup condition id (902 below) — never a value baked into the config."""
    import app.integrations.business_rules as business_rules_module

    monkeypatch.setattr(
        business_rules_module,
        "_load_template_child_conditions",
        lambda: {"dev": {"tpl-1": [{"ruleId": "4", "inputValue": "100334", "outputValue": "1%-2%"}]}},
    )

    condition_bodies = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/v1/apikeys/create-assign/rule/{STATIC_MARKUP_RULE_ID}"):
            return httpx.Response(200, json={"id": 301})
        if request.url.path.endswith(f"/v1/apikeys/create-assign/rule/{DYNAMIC_MARKUP_RULE_ID}"):
            return httpx.Response(200, json={"id": 401})
        if request.url.path.endswith("/rulevaluemappings"):
            body = json.loads(request.content.decode())
            condition_bodies.append(body)
            if body.get("parentRuleValueMappingId") == 902:
                return httpx.Response(201, json={"id": 903})
            condition_id = 901 if body["ruleId"] == STATIC_MARKUP_RULE_ID else 902
            return httpx.Response(201, json={"id": condition_id})
        if request.url.path.endswith("/refresh"):
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://br.test") as http_client:
        client = BusinessRulesClient(http_client)
        monkeypatch.setattr(client, "base_url", "http://br.test")
        monkeypatch.setattr(client.settings, "env", "dev")
        setup = await CrawlaBusinessRulesProvisioner(client).provision("smf-crawla-test", template_id="tpl-1")

    assert setup["status"] == "SUCCESS"
    child_bodies = [b for b in condition_bodies if b.get("inputValue") == "100334"]
    assert len(child_bodies) == 1
    assert child_bodies[0]["parentRuleValueMappingId"] == 902
    assert child_bodies[0]["outputValue"] == "1%-2%"
    assert setup["rules"]["4"]["template_child_condition_ids"] == ["903"]


@pytest.mark.asyncio
async def test_provision_no_op_when_template_id_not_in_config(monkeypatch):
    import app.integrations.business_rules as business_rules_module

    monkeypatch.setattr(
        business_rules_module,
        "_load_template_child_conditions",
        lambda: {"dev": {"tpl-1": [{"ruleId": "4", "inputValue": "100334"}]}},
    )

    condition_bodies = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/v1/apikeys/create-assign/rule/{STATIC_MARKUP_RULE_ID}"):
            return httpx.Response(200, json={"id": 301})
        if request.url.path.endswith(f"/v1/apikeys/create-assign/rule/{DYNAMIC_MARKUP_RULE_ID}"):
            return httpx.Response(200, json={"id": 401})
        if request.url.path.endswith("/rulevaluemappings"):
            body = json.loads(request.content.decode())
            condition_bodies.append(body)
            condition_id = 901 if body["ruleId"] == STATIC_MARKUP_RULE_ID else 902
            return httpx.Response(201, json={"id": condition_id})
        if request.url.path.endswith("/refresh"):
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://br.test") as http_client:
        client = BusinessRulesClient(http_client)
        monkeypatch.setattr(client, "base_url", "http://br.test")
        monkeypatch.setattr(client.settings, "env", "dev")
        setup = await CrawlaBusinessRulesProvisioner(client).provision(
            "smf-crawla-test", template_id="unknown-template"
        )

    assert setup["status"] == "SUCCESS"
    # Only the two normal static/dynamic conditions — nothing extra for an unmapped template.
    assert len(condition_bodies) == 2
