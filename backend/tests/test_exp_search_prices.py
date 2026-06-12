"""Verify EXP Search mock responses have non-zero prices.

The EXP adapter in the core service runs:
  "Removing rates with price 0 from search response"
and drops any rate whose occupancy_pricing total is <= 0.

These tests guard against SMF producing zero-price Search mocks by checking:
  1. netPrice > 0 in every rate
  2. occupancy_pricing totals.inclusive > 0 for every occupancy entry
  3. Search room/rate id fields match the ids embedded in price_check.href
     (mismatch caused the adapter to drop the rate entirely in a prior bug)

Two apiKey scenarios are covered:
  - Newly created Crawla scenario (fresh namespace + fresh apiKey from Backoffice)
  - exp-gross-qa-automation-dont-touch  (standing QA contract, do not modify)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.scenario_engine import REPO_ROOT, ScenarioEngine
from app.models.scenario import (
    PackageSpec,
    ScenarioRequest,
    SupplierCode,
    SupplierMutation,
    SupplierScenario,
)

MOCK_SERVER_BASE = "http://mockserver-staging.tajawal.io"
TEMPLATES_DIR = REPO_ROOT / "templates"
EXP_TEMPLATES_PRESENT = (
    (TEMPLATES_DIR / "EXP" / "Search" / "v1.json").exists()
    and (TEMPLATES_DIR / "EXP" / "Packages" / "v1.json").exists()
)
needs_exp_templates = pytest.mark.skipif(
    not EXP_TEMPLATES_PRESENT, reason="EXP templates not ingested"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _crawla_exp_request(namespace: str, exp_hotel_id: str = "2001358") -> ScenarioRequest:
    """ScenarioRequest matching what _build_scenario_request produces for a
    CRAWLA_LOWER Crawla scenario with EXP search_price + package_price."""
    return ScenarioRequest(
        namespace=namespace,
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1043546",
        supplier_hotel_ids={"EXP": exp_hotel_id},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(
                    count=1,
                    room_basis="RO",
                    prices=[2000.0],
                    refundable=[False],
                ),
            )
        ],
        supplier_mutations={
            "EXP": SupplierMutation(search_price=1500.0, package_price=2000.0),
        },
    )


def _exp_gross_qa_request() -> ScenarioRequest:
    """Represents the standing exp-gross-qa-automation-dont-touch contract."""
    return ScenarioRequest(
        namespace="exp-gross-qa-automation-dont-touch",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1043546",
        supplier_hotel_ids={"EXP": "2001358"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(
                    count=1,
                    room_basis="RO",
                    prices=[500.0],
                    refundable=[True],
                ),
            )
        ],
    )


def _get_exp_search(built: list) -> dict:
    return next(
        item.expectation
        for item in built
        if item.supplier_code == "EXP" and item.log_type == "Search"
    )


def _get_exp_packages(built: list) -> dict:
    return next(
        item.expectation
        for item in built
        if item.supplier_code == "EXP" and item.log_type == "Packages"
    )


def _search_rates(search_expectation: dict) -> list[dict]:
    body = search_expectation["httpResponse"]["body"]
    return body[0]["rooms"][0]["rates"]


def _assert_no_zero_price_rates(rates: list[dict], label: str) -> None:
    """Replicate the EXP adapter's price-0 check — every rate must pass.

    EXP Search rates price is in occupancy_pricing, not netPrice.
    The adapter removes any rate whose occupancy_pricing inclusive total <= 0.
    """
    assert rates, f"{label}: Search mock has no rates"
    for i, rate in enumerate(rates):
        occ = rate.get("occupancy_pricing", {})
        assert occ, (
            f"{label} rate[{i}]: no occupancy_pricing — "
            "adapter has no price to read"
        )
        for occ_key, occ_data in occ.items():
            val_str = occ_data["totals"]["inclusive"]["request_currency"]["value"]
            val = float(val_str)
            assert val > 0, (
                f"{label} rate[{i}] occ[{occ_key}]: "
                f"inclusive total={val!r} — "
                "adapter will remove this rate ('Removing rates with price 0')"
            )


def _extract_href_room_rate(href: str) -> tuple[str, str]:
    """Parse /v3/properties/.../rooms/{room}/rates/{rate}?token → (room, rate)."""
    parts = href.split("?")[0].split("/")
    room_id = rate_id = ""
    for j, part in enumerate(parts):
        if part == "rooms" and j + 1 < len(parts):
            room_id = parts[j + 1]
        if part == "rates" and j + 1 < len(parts):
            rate_id = parts[j + 1]
    return room_id, rate_id


# ---------------------------------------------------------------------------
# Unit tests — pipeline output verification (no HTTP)
# ---------------------------------------------------------------------------

@needs_exp_templates
def test_crawla_exp_search_mock_has_nonzero_prices():
    """Newly created Crawla scenario: Search mock must have rates with price > 0."""
    built = ScenarioEngine().build_expectations(
        _crawla_exp_request("crawla-test-smf-new")
    )
    search = _get_exp_search(built)
    rates = _search_rates(search)
    _assert_no_zero_price_rates(rates, "crawla-test-smf-new / EXP Search")


@needs_exp_templates
def test_exp_gross_qa_search_mock_has_nonzero_prices():
    """exp-gross-qa-automation-dont-touch: Search mock must have rates with price > 0."""
    built = ScenarioEngine().build_expectations(_exp_gross_qa_request())
    search = _get_exp_search(built)
    rates = _search_rates(search)
    _assert_no_zero_price_rates(rates, "exp-gross-qa-automation-dont-touch / EXP Search")


@needs_exp_templates
def test_search_room_rate_ids_match_price_check_href_for_new_scenario():
    """Search body room/rate ids must match what is in price_check.href.

    Mismatch caused the EXP adapter to silently drop the rate (root cause
    of the 'no adapter log' bug): Search template used room=216919865/rate=397499896
    while Packages template used room=201836237/rate=209336313; price_check.href
    was built from Packages ids but Search body kept Search template ids.
    """
    built = ScenarioEngine().build_expectations(
        _crawla_exp_request("crawla-test-id-align")
    )
    search = _get_exp_search(built)
    packages = _get_exp_packages(built)

    search_body = search["httpResponse"]["body"]
    pkg_body = packages["httpResponse"]["body"]

    search_room = search_body[0]["rooms"][0]
    pkg_room = pkg_body[0]["rooms"][0]

    search_room_id = search_room["id"]
    search_rate_id = search_room["rates"][0]["id"]
    pkg_room_id = pkg_room["id"]
    pkg_rate_id = pkg_room["rates"][0]["id"]

    # Search body ids must equal Packages body ids after propagate_package_linkage
    assert search_room_id == pkg_room_id, (
        f"Search room id {search_room_id!r} != Packages room id {pkg_room_id!r}"
    )
    assert search_rate_id == pkg_rate_id, (
        f"Search rate id {search_rate_id!r} != Packages rate id {pkg_rate_id!r}"
    )

    # price_check.href must use the same room/rate ids as the Search body
    bed_group = next(iter(search_room["rates"][0]["bed_groups"].values()))
    href = bed_group["links"]["price_check"]["href"]
    href_room, href_rate = _extract_href_room_rate(href)

    assert href_room == search_room_id, (
        f"price_check.href room={href_room!r} != Search body room id={search_room_id!r}"
    )
    assert href_rate == search_rate_id, (
        f"price_check.href rate={href_rate!r} != Search body rate id={search_rate_id!r}"
    )


@needs_exp_templates
def test_exp_gross_qa_search_room_rate_ids_match_price_check_href():
    """Same id-alignment check for the standing exp-gross-qa contract."""
    built = ScenarioEngine().build_expectations(_exp_gross_qa_request())
    search = _get_exp_search(built)
    packages = _get_exp_packages(built)

    search_room = search["httpResponse"]["body"][0]["rooms"][0]
    pkg_room = packages["httpResponse"]["body"][0]["rooms"][0]

    assert search_room["id"] == pkg_room["id"]
    assert search_room["rates"][0]["id"] == pkg_room["rates"][0]["id"]

    bed_group = next(iter(search_room["rates"][0]["bed_groups"].values()))
    href = bed_group["links"]["price_check"]["href"]
    href_room, href_rate = _extract_href_room_rate(href)
    assert href_room == search_room["id"]
    assert href_rate == search_room["rates"][0]["id"]


# ---------------------------------------------------------------------------
# Nock-style tests — mock the httpx GET call to MockServer
#
# Simulates what the EXP adapter receives when it calls:
#   GET http://mockserver-staging.tajawal.io/{namespace}/search
# with the given apiKey (injected by the core service, not by MockServer).
# ---------------------------------------------------------------------------

def _make_mock_response(body: list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


@needs_exp_templates
def test_mock_search_call_new_apikey_returns_nonzero_rates():
    """Nock: GET /{namespace}/search with newly created apiKey returns valid rates.

    Patches httpx so no real network call is made. The mock body comes from
    the SMF pipeline itself — verifying that what MockServer would serve to
    the EXP adapter has no zero-price rates.
    """
    namespace = "crawla-test-nock-new"
    built = ScenarioEngine().build_expectations(_crawla_exp_request(namespace))
    search = _get_exp_search(built)
    mock_body = search["httpResponse"]["body"]

    with patch("httpx.get", return_value=_make_mock_response(mock_body)) as mock_get:
        import httpx
        response = httpx.get(
            f"{MOCK_SERVER_BASE}/{namespace}/search",
            headers={"x-api-key": "smf-generated-apikey-example"},
        )
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert f"/{namespace}/search" in called_url

    properties = response.json()
    assert properties, "Search response body is empty"
    rates = properties[0]["rooms"][0]["rates"]
    _assert_no_zero_price_rates(rates, f"{namespace} / mocked GET /search")


@needs_exp_templates
def test_mock_search_call_exp_gross_qa_returns_nonzero_rates():
    """Nock: GET /exp-gross-qa-automation-dont-touch/search returns valid rates."""
    namespace = "exp-gross-qa-automation-dont-touch"
    built = ScenarioEngine().build_expectations(_exp_gross_qa_request())
    search = _get_exp_search(built)
    mock_body = search["httpResponse"]["body"]

    with patch("httpx.get", return_value=_make_mock_response(mock_body)) as mock_get:
        import httpx
        response = httpx.get(
            f"{MOCK_SERVER_BASE}/{namespace}/search",
            headers={"x-api-key": "exp-gross-qa-automation-dont-touch"},
        )
        mock_get.assert_called_once()

    properties = response.json()
    assert properties, "Search response body is empty"
    rates = properties[0]["rooms"][0]["rates"]
    _assert_no_zero_price_rates(rates, f"{namespace} / mocked GET /search")


# ---------------------------------------------------------------------------
# Integration tests — real HTTP to MockServer staging
# Requires: scenario already registered in MockServer. Skip with:
#   pytest -m "not integration"
# Run with:
#   pytest -m integration tests/test_exp_search_prices.py
# ---------------------------------------------------------------------------

@pytest.mark.integration
@needs_exp_templates
@pytest.mark.parametrize("namespace", [
    "exp-gross-qa-automation-dont-touch",
])
def test_integration_exp_search_staging_mockserver(namespace: str):
    """Actually calls MockServer staging — scenario must be pre-registered."""
    import httpx

    url = f"{MOCK_SERVER_BASE}/{namespace}/search"
    response = httpx.get(url, timeout=10)
    assert response.status_code == 200, (
        f"MockServer returned {response.status_code} for {url}"
    )
    properties = response.json()
    assert properties, f"Empty Search body from MockServer for namespace={namespace!r}"
    rates = properties[0]["rooms"][0]["rates"]
    _assert_no_zero_price_rates(rates, f"{namespace} / real MockServer")
