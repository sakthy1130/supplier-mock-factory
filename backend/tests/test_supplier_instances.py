"""The same supplier may appear more than once in one scenario.

Supplier code used to be the de-facto primary key for expectation ids, mock paths
and contract uids, so a second entry of the same code silently overwrote the first.
Every entry now carries an instance key — the bare code for the first entry, so
single-instance scenarios (and every already-stored record) keep their exact ids.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.contract_provisioner import ContractProvisioner
from app.core.mock_urls import extract_paths_from_built
from app.core.scenario_engine import REPO_ROOT, ScenarioEngine
from app.models.scenario import (
    PackageSpec,
    ScenarioRequest,
    SupplierCode,
    SupplierScenario,
    instance_key_for,
)

TEMPLATES_DIR = REPO_ROOT / "templates"

pytestmark = pytest.mark.skipif(
    not (TEMPLATES_DIR / "EXP" / "Packages" / "v1.json").exists(),
    reason="EXP templates not ingested",
)


def _two_exp_request() -> ScenarioRequest:
    def spec(price: float) -> PackageSpec:
        return PackageSpec(
            count=1,
            room_basis="RO",
            prices=[price],
            refundable=[True],
            booking_package_index=0,
        )

    return ScenarioRequest(
        namespace="qa-dup-001",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"EXP": "10469244"},
        suppliers=[
            SupplierScenario(code=SupplierCode.EXP, packages=spec(150.0)),
            SupplierScenario(code=SupplierCode.EXP, packages=spec(250.0)),
        ],
    )


def test_instance_key_keeps_first_entry_on_the_bare_code():
    assert instance_key_for("EXP", 1) == "EXP"
    assert instance_key_for("EXP", 2) == "EXP-2"


def test_instances_are_numbered_by_position():
    request = _two_exp_request()
    assert [s.instance for s in request.suppliers] == [1, 2]
    assert request.instance_keys() == ["EXP", "EXP-2"]


def test_a_caller_cannot_force_colliding_instance_numbers():
    """Instance is always recomputed from position, so a hand-written payload can't
    make two entries share a key (which would silently re-collide)."""
    request = _two_exp_request()
    request.suppliers[1].instance = 1
    revalidated = ScenarioRequest(**request.model_dump())
    assert revalidated.instance_keys() == ["EXP", "EXP-2"]


def test_two_instances_get_distinct_expectation_ids_and_paths():
    built = ScenarioEngine().build_expectations(_two_exp_request())

    first = {i.log_type: i for i in built if i.instance_key == "EXP"}
    second = {i.log_type: i for i in built if i.instance_key == "EXP-2"}
    assert first and second, "both EXP entries must produce expectations"
    assert set(first) == set(second)

    for log_type in first:
        id_a = first[log_type].expectation["id"]
        id_b = second[log_type].expectation["id"]
        path_a = first[log_type].expectation["httpRequest"]["path"]
        path_b = second[log_type].expectation["httpRequest"]["path"]
        assert id_a != id_b, f"{log_type} expectation id collides"
        assert path_a != path_b, f"{log_type} mock path collides"
        # Instance 1 keeps today's shape; instance 2 is isolated behind its own segment.
        assert id_a == f"smf-qa-dup-001-exp-{log_type}".lower()
        assert path_a.startswith("/qa-dup-001/")
        assert path_b.startswith("/qa-dup-001/exp-2/")


def test_price_check_href_follows_its_own_instance():
    """The EXP adapter reaches price-check via the href in the Packages body. If both
    entries carried the same href, instance 2 would book instance 1's rate."""
    built = ScenarioEngine().build_expectations(_two_exp_request())

    hrefs = {}
    for item in built:
        if item.log_type != "Packages":
            continue
        rate = item.expectation["httpResponse"]["body"][0]["rooms"][0]["rates"][0]
        bed_group = next(iter(rate["bed_groups"].values()))
        hrefs[item.instance_key] = bed_group["links"]["price_check"]["href"]

    assert hrefs["EXP"].startswith("/qa-dup-001/v3/properties/")
    assert hrefs["EXP-2"].startswith("/qa-dup-001/exp-2/v3/properties/")

    prebook = {i.instance_key: i.expectation["httpRequest"]["path"] for i in built if i.log_type == "PreBooking"}
    for key, href in hrefs.items():
        assert href.split("?", 1)[0] == prebook[key], f"{key} href must hit its own PreBooking mock"


def test_paths_and_prices_are_keyed_per_instance():
    request = _two_exp_request()
    built = ScenarioEngine().build_expectations(request)

    paths = extract_paths_from_built(built)
    assert set(paths) == {"EXP", "EXP-2"}
    assert paths["EXP"]["Packages"] == "/qa-dup-001/package"
    assert paths["EXP-2"]["Packages"] == "/qa-dup-001/exp-2/package"

    # Each entry keeps its own price — the point of adding the supplier twice.
    def total(instance_key: str) -> float:
        item = next(i for i in built if i.instance_key == instance_key and i.log_type == "Packages")
        rate = item.expectation["httpResponse"]["body"][0]["rooms"][0]["rates"][0]
        return float(rate["occupancy_pricing"]["2"]["totals"]["inclusive"]["billable_currency"]["value"])

    assert total("EXP") != total("EXP-2")


@pytest.mark.asyncio
async def test_two_contracts_are_created_with_distinct_uids():
    backoffice = MagicMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=False)
    backoffice.create_contract = AsyncMock(side_effect=["mongo-1", "mongo-2"])

    provisioner = ContractProvisioner(backoffice=backoffice)
    provisioner.settings.exp_reference_contract_id = ""

    contract_ids = await provisioner.create_contracts(
        _two_exp_request(),
        {
            "EXP": {"Search": "/qa-dup-001/search", "Packages": "/qa-dup-001/package"},
            "EXP-2": {"Search": "/qa-dup-001/exp-2/search", "Packages": "/qa-dup-001/exp-2/package"},
        },
        "http://mock-server",
    )

    assert contract_ids == {"EXP": "mongo-1", "EXP-2": "mongo-2"}

    bodies = [call.args[0] for call in backoffice.create_contract.await_args_list]
    assert [b["uid"] for b in bodies] == ["smf-qa-dup-001-exp", "smf-qa-dup-001-exp-2"]
    # Each contract must point at ITS OWN mocks, not the other entry's.
    assert bodies[0]["opt"]["overridePackagesUrl"] == "http://mock-server/qa-dup-001/package"
    assert bodies[1]["opt"]["overridePackagesUrl"] == "http://mock-server/qa-dup-001/exp-2/package"


def test_per_instance_mutation_only_hits_its_own_instance():
    """supplier_mutations is addressed by instance key. Keyed by bare code it would
    apply to every entry of that code, which is what the engine used to do."""
    from app.models.scenario import SupplierMutation

    request = _two_exp_request()
    request.supplier_mutations = {"EXP-2": SupplierMutation(room_name="Second Instance Room")}

    built = ScenarioEngine().build_expectations(request)

    def room_names(instance_key: str) -> str:
        item = next(i for i in built if i.instance_key == instance_key and i.log_type == "Packages")
        return json.dumps(item.expectation["httpResponse"]["body"])

    assert "Second Instance Room" in room_names("EXP-2")
    assert "Second Instance Room" not in room_names("EXP")


def test_template_may_carry_the_same_supplier_twice():
    """Templates used to reject duplicates outright ("each supplier can only appear
    once per template"), which blocked saving a two-EXP scenario as a template."""
    from app.models.scenario_template import (
        ScenarioTemplateCreate,
        SupplierTemplatePackages,
        TemplatePackageRow,
    )

    def entry(price: float) -> SupplierTemplatePackages:
        return SupplierTemplatePackages(
            supplier="EXP",
            packages=[TemplatePackageRow(room_name="Room", room_basis="RO", price=price)],
        )

    created = ScenarioTemplateCreate(
        label="two exp",
        atg_hotel_id="1446194",
        suppliers=[entry(150.0), entry(250.0)],
    )

    assert [e.supplier for e in created.suppliers] == ["EXP", "EXP"]
    assert [e.packages[0].price for e in created.suppliers] == [150.0, 250.0]


def test_automation_api_turns_a_duplicate_template_into_two_instances():
    from datetime import datetime

    from app.api.routes.run_template import build_scenario_request_from_template
    from app.models.run_template import RunTemplateRequest
    from app.models.scenario_template import (
        ScenarioTemplate,
        SupplierTemplatePackages,
        TemplatePackageRow,
    )

    def entry(price: float) -> SupplierTemplatePackages:
        return SupplierTemplatePackages(
            supplier="EXP",
            packages=[TemplatePackageRow(room_name="Room", room_basis="RO", price=price)],
        )

    template = ScenarioTemplate(
        id="tmpl-dup",
        label="two exp",
        description="",
        atg_hotel_id="1446194",
        created_at=datetime(2026, 8, 18),
        suppliers=[entry(150.0), entry(250.0)],
    )

    request = build_scenario_request_from_template(
        template,
        RunTemplateRequest(environment="stg"),
        namespace="qa-auto-dup",
        check_in="2026-09-10",
        check_out="2026-09-14",
        hotel_id="1446194",
        template_id="tmpl-dup",
    )

    assert request.instance_keys() == ["EXP", "EXP-2"]
    assert [s.packages.prices[0] for s in request.suppliers] == [150.0, 250.0]


def test_single_supplier_scenario_is_unchanged():
    """Regression guard: one entry must produce exactly the pre-instance ids/paths."""
    request = ScenarioRequest(
        namespace="qa-dup-001",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"EXP": "10469244"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(count=1, room_basis="RO", prices=[150.0], refundable=[True]),
            )
        ],
    )

    built = ScenarioEngine().build_expectations(request)

    assert request.instance_keys() == ["EXP"]
    assert {i.instance_key for i in built} == {"EXP"}
    packages = next(i for i in built if i.log_type == "Packages")
    assert packages.expectation["id"] == "smf-qa-dup-001-exp-packages"
    assert packages.expectation["httpRequest"]["path"] == "/qa-dup-001/package"
