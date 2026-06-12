import json
from pathlib import Path

import pytest

from app.core.linkage_validator import LinkageError, LinkageValidator
from app.core.mock_urls import build_mock_opt_urls, extract_paths_from_built
from app.core.namespace import build_expectation_id
from app.core.scenario_engine import REPO_ROOT, ScenarioEngine
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierCode, SupplierMutation, SupplierScenario

TEMPLATES_DIR = REPO_ROOT / "templates"


def _request(**overrides) -> ScenarioRequest:
    payload = {
        "namespace": "qa-test-001",
        "check_in": "2026-09-01",
        "check_out": "2026-09-03",
        "atg_hotel_id": "1446194",
        "supplier_hotel_ids": {"HBS": "99999"},
        "suppliers": [
            SupplierScenario(
                code=SupplierCode.HBS,
                packages=PackageSpec(
                    count=2,
                    room_basis="RO",
                    prices=[100.0, 200.0],
                    refundable=[True, False],
                ),
            )
        ],
    }
    payload.update(overrides)
    return ScenarioRequest(**payload)


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Packages" / "v1.json").exists(),
    reason="HBS templates not ingested",
)
def test_scenario_engine_builds_hbs_expectations_with_namespace():
    engine = ScenarioEngine()
    built = engine.build_expectations(_request())

    assert built
    packages = next(item for item in built if item.log_type == "Packages")
    assert packages.supplier_code == "HBS"
    assert packages.expectation["id"] == build_expectation_id("qa-test-001", "HBS", "Packages")

    rates = (
        packages.expectation["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"]
    )
    assert len(rates) == 2
    assert rates[0]["net"] == "100.0"
    assert rates[1]["net"] == "200.0"
    assert rates[0]["boardCode"] == "RO"
    assert rates[0]["rateClass"] == "REF"
    assert rates[1]["rateClass"] == "NRF"

    for item in built:
        http_request = item.expectation.get("httpRequest", {})
        assert "body" not in http_request
        assert "headers" not in http_request

    search = next(item for item in built if item.log_type == "Search")
    assert search.expectation["httpRequest"]["path"] == "/hotel-api/1.0/hotels/search"
    search_hotels = search.expectation["httpResponse"]["body"]["hotels"]["hotels"]
    assert len(search_hotels) == 1
    assert search_hotels[0]["code"] == 99999
    prebook = next(item for item in built if item.log_type == "PreBooking")
    assert prebook.expectation["httpRequest"]["path"] == "/hotel-api/1.0/checkrates/preBooking"
    booking = next(item for item in built if item.log_type == "Booking")
    assert booking.expectation["httpRequest"]["path"] == "/hotel-api/1.2/bookings/booking"


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Packages" / "v1.json").exists(),
    reason="HBS templates not ingested",
)
def test_scenario_engine_preserves_hbs_package_count_with_crawla_mutation():
    request = _request(
        supplier_mutations={
            "HBS": SupplierMutation(
                package_price=3363.81,
                room_name="Double Room",
                room_basis="HB",
            )
        }
    )

    built = ScenarioEngine().build_expectations(request)
    packages = next(item for item in built if item.log_type == "Packages")
    rates = packages.expectation["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"]

    assert len(rates) == 2
    assert rates[0]["net"] == "3363.81"
    assert rates[1]["net"] == "3363.81"
    assert rates[0]["boardCode"] == "HB"
    assert rates[1]["boardCode"] == "HB"


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "EXP" / "Packages" / "v1.json").exists(),
    reason="EXP templates not ingested",
)
def test_scenario_engine_builds_exp_expectations():
    engine = ScenarioEngine()
    request = ScenarioRequest(
        namespace="qa-exp-001",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "88888"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(count=2, room_basis="RO", prices=[150.0, 250.0], refundable=[True, False]),
            )
        ],
    )
    built = engine.build_expectations(request)
    packages = next(item for item in built if item.log_type == "Packages")
    assert packages.expectation["httpRequest"]["path"] == "/qa-exp-001/package"
    package_properties = packages.expectation["httpResponse"]["body"]
    rates = package_properties[0]["rooms"][0]["rates"]
    assert len(rates) == 2
    assert rates[0]["refundable"] is True
    assert rates[1]["refundable"] is False

    search = next(item for item in built if item.log_type == "Search")
    prebook = next(item for item in built if item.log_type == "PreBooking")
    booking = next(item for item in built if item.log_type == "Booking")
    get_order = next(item for item in built if item.log_type == "GetOrder")

    assert search.expectation["httpRequest"]["path"] == "/qa-exp-001/search"
    property_id = package_properties[0]["property_id"]
    room_id = package_properties[0]["rooms"][0]["id"]
    rate_id = rates[0]["id"]
    assert prebook.expectation["httpRequest"]["path"] == (
        f"/v3/properties/{property_id}/rooms/{room_id}/rates/{rate_id}"
    )
    assert booking.expectation["httpRequest"]["path"] == "/v3/itineraries"
    assert get_order.expectation["httpRequest"]["path"].startswith("/v3/itineraries/")
    bed_group = next(iter(rates[0]["bed_groups"].values()))
    price_check_href = bed_group["links"]["price_check"]["href"]
    assert price_check_href.startswith(
        f"/v3/properties/{property_id}/rooms/{room_id}/rates/{rate_id}"
    )
    assert rates[0]["sale_scenario"]["distribution"] is True
    assert len(search.expectation["httpResponse"]["body"][0]["rooms"][0]["rates"]) == 1

    paths = extract_paths_from_built(built)["EXP"]
    opt = build_mock_opt_urls("http://mock-server", paths, "EXP")
    assert opt["overrideSearchUrl"] == "http://mock-server/qa-exp-001/search"
    assert opt["overridePackagesUrl"] == "http://mock-server/qa-exp-001/package"
    assert opt["overrideBookingUrl"] == "http://mock-server/v3/itineraries"
    assert opt["overrideRetrieveBookingUrl"].startswith("http://mock-server/v3/itineraries/")


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "EXP" / "Search" / "v1.json").exists(),
    reason="EXP templates not ingested",
)
def test_scenario_engine_updates_exp_search_with_crawla_search_price():
    engine = ScenarioEngine()
    request = ScenarioRequest(
        namespace="qa-exp-crawla-search",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1043546",
        supplier_hotel_ids={"EXP": "2001358"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(count=1, room_basis="RO", prices=[7600.0], refundable=[False]),
            )
        ],
        supplier_mutations={
            "EXP": SupplierMutation(search_price=7500.0, package_price=7600.0),
        },
    )

    built = engine.build_expectations(request)
    search = next(item for item in built if item.log_type == "Search")
    properties = search.expectation["httpResponse"]["body"]
    rate = properties[0]["rooms"][0]["rates"][0]
    occupancy_pricing = rate["occupancy_pricing"]["2"]

    assert len(properties) == 1
    assert properties[0]["property_id"] == "2001358"
    assert occupancy_pricing["totals"]["inclusive"]["request_currency"]["value"] == "7500.00"
    assert occupancy_pricing["totals"]["exclusive"]["request_currency"]["value"] == "6122.45"
    assert occupancy_pricing["nightly"][0][0]["value"] == "1224.49"
    assert occupancy_pricing["nightly"][0][1]["value"] == "153.06"


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "RHK" / "Packages" / "v1.json").exists(),
    reason="RHK templates not ingested",
)
def test_scenario_engine_builds_rhk_expectations():
    engine = ScenarioEngine()
    request = ScenarioRequest(
        namespace="qa-rhk-001",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"RHK": "7830881"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.RHK,
                packages=PackageSpec(count=2, room_basis="RO", prices=[100.0, 200.0], refundable=[True, False]),
            )
        ],
    )
    built = engine.build_expectations(request)
    packages = next(item for item in built if item.log_type == "Packages")
    rates = packages.expectation["httpResponse"]["body"]["data"]["hotels"][0]["rates"]
    assert len(rates) == 2
    assert rates[0]["meal"] == "nomeal"
    assert rates[0]["payment_options"]["payment_types"][0]["show_amount"] == "100.00"


@pytest.mark.skipif(
    not (TEMPLATES_DIR / "HBS" / "Packages" / "v1.json").exists()
    or not (TEMPLATES_DIR / "EXP" / "Packages" / "v1.json").exists(),
    reason="HBS/EXP templates not ingested",
)
def test_scenario_engine_builds_hbs_and_exp_without_rhk():
    """Regression: HBS+EXP multi-supplier build must not pull in RHK."""
    engine = ScenarioEngine()
    request = ScenarioRequest(
        namespace="qa-hbs-exp-only",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "156652", "EXP": "50878533"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.HBS,
                packages=PackageSpec(count=2, room_basis="RO", prices=[100.0, 200.0], refundable=[True, False]),
            ),
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(count=2, room_basis="RO", prices=[150.0, 250.0], refundable=[True, False]),
            ),
        ],
    )
    built = engine.build_expectations(request)
    supplier_codes = {item.supplier_code for item in built}
    assert supplier_codes == {"HBS", "EXP"}
    assert "RHK" not in supplier_codes
    assert all("rhk" not in item.expectation.get("id", "").lower() for item in built)


def test_linkage_validator_detects_hbs_rate_mismatch():
    validator = LinkageValidator()
    packages = json.loads((TEMPLATES_DIR / "HBS" / "Packages" / "v1.json").read_text())
    prebook = json.loads((TEMPLATES_DIR / "HBS" / "PreBooking" / "v1.json").read_text())
    prebook.setdefault("httpRequest", {}).setdefault("body", {}).setdefault("json", {})["rooms"] = [
        {"rateKey": "mismatch"}
    ]
    with pytest.raises(LinkageError):
        validator.validate(
            {"Packages": packages, "PreBooking": prebook},
            "HBS",
            PackageSpec(count=1, room_basis="RO", prices=[100.0]),
        )
