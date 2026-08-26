"""Unit tests for the automation API's scenario-request builder
(build_scenario_request_from_template) and booking-selection derivation.

Covers the two opt-in behaviors added to /api/v1/run-template:
- Booking: off unless the request passes a valid booking_package_index.
- SmartBooking: inherits the template's sb_enabled unless the request overrides
  it; each supplier's contract routes by its template assignment_target.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.api.routes.run_template import (
    _booking_selection_from_request,
    build_scenario_request_from_template,
)
from app.models.run_template import RunTemplateRequest
from app.models.scenario_template import (
    ScenarioTemplate,
    SupplierTemplatePackages,
    TemplatePackageRow,
)

BUILD_KW = dict(
    namespace="qa-auto-01",
    check_in="2026-09-10",
    check_out="2026-09-14",
    hotel_id="1500003",
    template_id="tmpl-1",
)


def _template(*, sb_enabled=False, targets=None, hbs_pkgs=2) -> ScenarioTemplate:
    """A 2-supplier template (HBS with hbs_pkgs packages, EXT with 1). targets
    maps supplier code -> assignment_target string; default apikey."""
    targets = targets or {}
    hbs_rows = [
        TemplatePackageRow(room_name=f"HBS Room {i}", room_basis="RO", price=100.0 + i, refundable=True)
        for i in range(hbs_pkgs)
    ]
    return ScenarioTemplate(
        id="tmpl-1",
        label="Auto",
        description="",
        atg_hotel_id="1500003",
        sb_enabled=sb_enabled,
        created_at=datetime(2026, 8, 3),
        suppliers=[
            SupplierTemplatePackages(
                supplier="HBS", packages=hbs_rows, assignment_target=targets.get("HBS", "apikey")
            ),
            SupplierTemplatePackages(
                supplier="EXT",
                packages=[TemplatePackageRow(room_name="EXT Room", room_basis="BB", price=200.0, refundable=False)],
                assignment_target=targets.get("EXT", "apikey"),
            ),
        ],
    )


# --- Booking opt-in ---------------------------------------------------------


def test_booking_disabled_by_default():
    req = build_scenario_request_from_template(_template(), RunTemplateRequest(environment="stg"), **BUILD_KW)
    assert all(s.packages.booking_package_index is None for s in req.suppliers)
    assert _booking_selection_from_request(req) is None


def test_booking_enabled_with_valid_index():
    req = build_scenario_request_from_template(
        _template(), RunTemplateRequest(environment="stg", booking_package_index=1), **BUILD_KW
    )
    hbs = next(s for s in req.suppliers if s.code.value == "HBS")
    assert hbs.packages.booking_package_index == 1
    sel = _booking_selection_from_request(req)
    assert sel == {"supplier": "HBS", "price": 101.0, "board": "RO", "room_name": "HBS Room 1"}


def test_booking_index_out_of_range_for_supplier_is_dropped():
    # HBS has 2 packages (valid index 0,1); EXT has 1 (index 1 invalid).
    req = build_scenario_request_from_template(
        _template(), RunTemplateRequest(environment="stg", booking_package_index=1), **BUILD_KW
    )
    hbs = next(s for s in req.suppliers if s.code.value == "HBS")
    ext = next(s for s in req.suppliers if s.code.value == "EXT")
    assert hbs.packages.booking_package_index == 1
    assert ext.packages.booking_package_index is None  # out of range -> no booking


def test_booking_index_out_of_range_everywhere_yields_no_selection():
    req = build_scenario_request_from_template(
        _template(hbs_pkgs=1), RunTemplateRequest(environment="stg", booking_package_index=5), **BUILD_KW
    )
    assert all(s.packages.booking_package_index is None for s in req.suppliers)
    assert _booking_selection_from_request(req) is None


# --- SmartBooking routing ---------------------------------------------------


def test_sb_off_by_default_all_contracts_to_apikey():
    req = build_scenario_request_from_template(_template(), RunTemplateRequest(environment="stg"), **BUILD_KW)
    assert req.sb_enabled is False
    assert req.sb_config is None
    assert req.apikey_contract_codes() == ["HBS", "EXT"]
    assert req.sbgroup_contract_codes() == []


def test_sb_inherited_from_template_with_routing():
    tmpl = _template(sb_enabled=True, targets={"HBS": "apikey", "EXT": "both"})
    req = build_scenario_request_from_template(tmpl, RunTemplateRequest(environment="stg"), **BUILD_KW)
    assert req.sb_enabled is True
    assert req.sb_config is not None  # default config materialized
    assert req.apikey_contract_codes() == ["HBS", "EXT"]  # EXT is 'both'
    assert req.sbgroup_contract_codes() == ["EXT"]


def test_request_override_forces_sb_on():
    tmpl = _template(sb_enabled=False, targets={"EXT": "sbgroup"})
    req = build_scenario_request_from_template(
        tmpl, RunTemplateRequest(environment="stg", sb_enabled=True), **BUILD_KW
    )
    assert req.sb_enabled is True
    assert req.apikey_contract_codes() == ["HBS"]  # only apikey/both
    assert req.sbgroup_contract_codes() == ["EXT"]


def test_request_override_forces_sb_off():
    tmpl = _template(sb_enabled=True, targets={"EXT": "sbgroup"})
    req = build_scenario_request_from_template(
        tmpl, RunTemplateRequest(environment="stg", sb_enabled=False), **BUILD_KW
    )
    assert req.sb_enabled is False
    assert req.sb_config is None
    assert req.apikey_contract_codes() == ["HBS", "EXT"]  # SB off -> all to apiKey


def test_sb_on_with_no_group_member_is_rejected():
    tmpl = _template(sb_enabled=True, targets={"HBS": "apikey", "EXT": "apikey"})
    with pytest.raises(ValidationError, match="no supplier targets the SB group"):
        build_scenario_request_from_template(tmpl, RunTemplateRequest(environment="stg"), **BUILD_KW)


# --- EXP explicit pricing -------------------------------------------------


def _exp_template(rows: list[TemplatePackageRow]) -> ScenarioTemplate:
    return ScenarioTemplate(
        id="tmpl-exp",
        label="EXP explicit",
        description="",
        atg_hotel_id="1500003",
        created_at=datetime(2026, 8, 24),
        suppliers=[SupplierTemplatePackages(supplier="EXP", packages=rows)],
    )


def test_explicit_pricing_carries_from_a_saved_template():
    """A template that stores the three amounts must replay them, or an automation run
    prices differently from the UI scenario it was saved from."""
    template = _exp_template([
        TemplatePackageRow(
            room_name="EXP Room",
            price=1120.0,
            original_price_with_vat=1000.0,
            markup=120.0,
        )
    ])
    request = build_scenario_request_from_template(
        template=template, request_data=RunTemplateRequest(), **BUILD_KW
    )
    spec = request.suppliers[0].packages
    assert spec.has_explicit_pricing
    assert (spec.prices, spec.original_price_with_vat, spec.markup) == ([1120.0], [1000.0], [120.0])


def test_a_template_without_the_amounts_stays_price_only():
    """Every template saved before the fields existed keeps building the same spec."""
    template = _exp_template([TemplatePackageRow(room_name="EXP Room", price=1120.0)])
    request = build_scenario_request_from_template(
        template=template, request_data=RunTemplateRequest(), **BUILD_KW
    )
    spec = request.suppliers[0].packages
    assert not spec.has_explicit_pricing
    assert spec.original_price_with_vat == [] and spec.markup == []


def test_a_template_with_the_amounts_on_only_some_rows_is_ignored_not_rejected():
    """Partial rows cannot be sent as a list (PackageSpec rejects ragged input), so the
    builder drops them rather than failing the whole automation run."""
    template = _exp_template([
        TemplatePackageRow(
            room_name="A", price=1120.0, original_price_with_vat=1000.0, markup=120.0
        ),
        TemplatePackageRow(room_name="B", price=500.0),
    ])
    request = build_scenario_request_from_template(
        template=template, request_data=RunTemplateRequest(), **BUILD_KW
    )
    assert not request.suppliers[0].packages.has_explicit_pricing


# --- BR markup ------------------------------------------------------------


def test_markup_values_thread_from_the_run_request():
    """The automation API is how scripted runs set markup; unset must stay unset so the
    provisioner applies its own defaults rather than a blank string."""
    request = build_scenario_request_from_template(
        template=_template(),
        request_data=RunTemplateRequest(static_markup="20", dynamic_markup="30%-40%"),
        **BUILD_KW,
    )
    assert (request.static_markup, request.dynamic_markup) == ("20%", "30%-40%")


def test_no_markup_on_the_run_request_leaves_the_scenario_unset():
    request = build_scenario_request_from_template(
        template=_template(), request_data=RunTemplateRequest(), **BUILD_KW
    )
    assert request.static_markup is None and request.dynamic_markup is None
