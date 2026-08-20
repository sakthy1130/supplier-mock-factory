"""The SB config create body must match the portal's stored shape: top-level
survey1/board/cancellationPolicy/includeNewSession/priceMarginToUpgrade mirrors
plus string survey flags — otherwise the config is inert and a grouped contract
never engages in search."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.sb_group_provisioner import SBGroupProvisioner
from app.models.scenario import SBScenarioConfig


class _Resp:
    status_code = 200

    def json(self):
        return {"_id": "cfg-1", "name": "smf-sb-x", "created_at": 1}

    text = "ok"


def test_apikey_embeds_group_contracts():
    """The apiKey's opt.smartBooking.groups[0] must carry the group's contracts,
    or the SB engine never pulls the group contract into the SB-session search
    (supplierConfigList shows only the apiKey's own contracts)."""
    from app.core.apikey_provisioner import _build_api_key_body

    body = _build_api_key_body(
        {"opt": {}},
        "smf-qa-x",
        "node-1",
        ["c-hbs"],
        sb_config_data={"_id": "cfg-1", "name": "smf-sb-x", "created_at": 0},
        sb_group_data={"_id": "grp-1", "name": "smf-sb-x", "isActive": True, "contracts": ["c-ext"], "submit": True, "created_at": 0},
        sb_enabled=True,
    )
    group = body["opt"]["smartBooking"]["groups"][0]
    assert group["contracts"] == ["c-ext"]


def test_sb_off_neutralizes_template_smart_booking():
    """The template apiKey (tj-htl-test-bookable) carries a live opt.smartBooking on
    stg — isEnabled=true plus the standing Expedia/NetSupplier/HBS groups. A scenario
    created with SB off must not inherit it, or the "non-SB" apiKey silently books
    through SmartBooking."""
    from app.core.apikey_provisioner import _build_api_key_body

    template = {
        "opt": {
            "smartBooking": {
                "configuration": {"_id": "cfg-shared", "name": "Smart Book Configuration"},
                "groups": [{"_id": "g1", "name": "Expedia Normal"}, {"_id": "g2", "name": "NetSupplier"}],
                "isEnabled": True,
            }
        }
    }

    body = _build_api_key_body(template, "smf-qa-x", "node-1", ["c-exp"])

    smart_booking = body["opt"]["smartBooking"]
    assert smart_booking["isEnabled"] is False
    assert smart_booking["groups"] == []
    # The template dict itself must not be mutated — it is reused across calls.
    assert template["opt"]["smartBooking"]["isEnabled"] is True


def test_sb_off_without_template_smart_booking_is_a_noop():
    from app.core.apikey_provisioner import _build_api_key_body

    body = _build_api_key_body({"opt": {}}, "smf-qa-x", "node-1", ["c-exp"])

    assert "smartBooking" not in body["opt"]


@pytest.mark.asyncio
async def test_sb_config_body_matches_portal_shape():
    backoffice = MagicMock()
    backoffice.base_url = "http://backoffice"
    client = MagicMock()
    client.post = AsyncMock(return_value=_Resp())
    backoffice._get_client = MagicMock(return_value=client)
    backoffice.auth_headers = AsyncMock(return_value={})

    prov = SBGroupProvisioner(backoffice=backoffice)
    await prov._create_sb_config_entity(SBScenarioConfig(), "qa-x")

    body = client.post.await_args.kwargs["json"]

    # top-level mirrors the SB engine reads
    for key in ("survey1", "board", "cancellationPolicy", "includeNewSession", "priceMarginToUpgrade"):
        assert key in body, f"missing top-level {key}"
    # nested block still present
    assert "survey1" in body["groupConfiguration"]
    assert "priceMarginToUpgrade" in body["price"]
    # survey flags are strings, not booleans
    assert body["survey1"]["class"] in ("true", "false")
    assert body["groupConfiguration"]["survey1"]["bedding"] in ("true", "false")
    # Nested groupConfiguration keeps the portal's stored form defaults
    # (all-true survey, board/CP off); the top-level fields carry the tuned
    # values the SB engine reads — they are intentionally decoupled.
    assert body["groupConfiguration"]["survey1"] == {"class": "true", "type": "true", "view": "true", "bedding": "true"}
    assert body["groupConfiguration"]["board"] is False
    # Defaults align with the working reference config.
    assert body["survey1"]["type"] == "false" and body["survey1"]["view"] == "false"
    assert body["board"] is True and body["cancellationPolicy"] is True
    assert body["price"]["priceMarginPercentage"] == "50"
    assert body["price"]["priceMarginToUpgrade"] == "50"
    assert body["priceMarginToUpgrade"] == ""
    assert body["opt"]["considerOriginalPackage"] is True
