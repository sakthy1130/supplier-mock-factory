"""SmartBooking per-supplier contract routing: request model split + guard."""

from __future__ import annotations

import pytest

from app.models.scenario import (
    AssignmentTarget,
    PackageSpec,
    ScenarioRequest,
    SupplierCode,
    SupplierScenario,
)


def _request(targets, *, sb_enabled=False, sb_config=None):
    return ScenarioRequest(
        namespace="qa-sb-test",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1010102",
        sb_enabled=sb_enabled,
        sb_config=sb_config,
        suppliers=[
            SupplierScenario(
                code=SupplierCode(code),
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]),
                assignment_target=AssignmentTarget(target),
            )
            for code, target in targets
        ],
    )


def test_sb_enabled_materializes_default_config():
    req = _request([("HBS", "both")], sb_enabled=True)
    assert req.sb_config is not None


def test_split_apikey_sbgroup_both():
    req = _request(
        [("HBS", "apikey"), ("EXP", "sbgroup"), ("EXT", "both")],
        sb_enabled=True,
    )
    assert req.apikey_contract_codes() == ["HBS", "EXT"]
    assert req.sbgroup_contract_codes() == ["EXP", "EXT"]


def test_sb_off_sends_all_to_apikey_ignoring_target():
    # Targets are ignored with SB off; every supplier goes to the apiKey.
    req = _request([("HBS", "apikey"), ("EXP", "sbgroup")], sb_enabled=False)
    assert req.sb_config is None
    assert req.apikey_contract_codes() == ["HBS", "EXP"]
    assert req.sbgroup_contract_codes() == ["EXP"]  # informational; unused when SB off


def test_default_target_is_apikey():
    req = ScenarioRequest(
        namespace="qa-sb-test",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1010102",
        suppliers=[
            SupplierScenario(
                code=SupplierCode.HBS,
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]),
            )
        ],
    )
    assert req.suppliers[0].assignment_target == AssignmentTarget.apikey


def test_sb_on_without_group_member_rejected():
    with pytest.raises(ValueError):
        _request([("HBS", "apikey"), ("EXP", "apikey")], sb_enabled=True)
