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


# ---------------------------------------------------------------------------
# Explicit pricing — total / originalPriceWithVAT / markup
# ---------------------------------------------------------------------------

def _explicit_request(namespace: str = "exp-explicit-pricing") -> ScenarioRequest:
    """One EXP package priced explicitly: 1000 net + 120 markup = 1120 gross."""
    return ScenarioRequest(
        namespace=namespace,
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
                    prices=[1120.0],
                    refundable=[False],
                    original_price_with_vat=[1000.0],
                    markup=[120.0],
                ),
            )
        ],
    )


def _totals(expectation: dict) -> dict:
    """The first occupancy's totals, as {node: request_currency value}.

    Finds occupancy_pricing wherever it sits: Search/Packages wrap it in a property →
    rooms → rates list, while PreBooking's body IS the rate.
    """
    from app.plugins.json_utils import walk_nodes

    for node in walk_nodes(expectation["httpResponse"]["body"]):
        if not isinstance(node, dict):
            continue
        occupancy = node.get("occupancy_pricing")
        if not isinstance(occupancy, dict) or not occupancy:
            continue
        totals = occupancy[next(iter(occupancy))].get("totals")
        if not isinstance(totals, dict):
            continue
        return {
            key: value["request_currency"]["value"]
            for key, value in totals.items()
            if isinstance(value, dict) and isinstance(value.get("request_currency"), dict)
        }
    raise AssertionError("no occupancy_pricing totals found in expectation")


def _template_tax_ratio() -> float:
    """exclusive / inclusive as captured in templates/EXP/Packages/v1.json."""
    template = json.loads(
        (TEMPLATES_DIR / "EXP" / "Packages" / "v1.json").read_text(encoding="utf-8")
    )
    totals = _totals(template)
    return float(totals["exclusive"]) / float(totals["inclusive"])


@needs_exp_templates
def test_explicit_pricing_pins_inclusive_and_marketing_fee():
    """totals.inclusive is what the adapter reports as total, totals.marketing_fee is what
    it reports as markup.dynamic (getRoomRateInfo in hotel-connectivity-exp-adapter), so
    those two nodes must carry the scenario's numbers exactly — not the template's ratio."""
    built = ScenarioEngine().build_expectations(_explicit_request())
    totals = _totals(_get_exp_packages(built))

    assert totals["inclusive"] == "1120.00"
    assert totals["marketing_fee"] == "120.00"


@needs_exp_templates
def test_explicit_pricing_keeps_the_templates_tax_proportion():
    """The adapter derives tax as inclusive − exclusive. Writing inclusive alone would
    silently change the tax, so exclusive is rescaled with it."""
    totals = _totals(_get_exp_packages(ScenarioEngine().build_expectations(_explicit_request())))
    assert float(totals["exclusive"]) == pytest.approx(1120.0 * _template_tax_ratio(), abs=0.02)
    # And the tax it implies is a real amount, not zero — exclusive did not just track
    # inclusive.
    assert float(totals["inclusive"]) - float(totals["exclusive"]) > 0


@needs_exp_templates
def test_explicit_pricing_agrees_across_search_and_packages():
    """Search and Packages must report the SAME markup for the same package.

    They are captured from different SIDs, so their templates carry different
    marketing_fee/inclusive ratios — scaling alone gives the adapter two different markups
    for one package (107.78 vs 117.11 on the current templates). Setting the value fixes
    both to what was asked for.
    """
    built = ScenarioEngine().build_expectations(_explicit_request())
    for log_type in ("Search", "Packages"):
        expectation = next(
            item.expectation for item in built
            if item.supplier_code == "EXP" and item.log_type == log_type
        )
        totals = _totals(expectation)
        assert totals["inclusive"] == "1120.00", log_type
        assert totals["marketing_fee"] == "120.00", log_type


@needs_exp_templates
def test_prebooking_pricing_is_untouched_by_the_scenario():
    """Documents a PRE-EXISTING gap, not a decision of the explicit-pricing work.

    EXP PreBooking's body is a bare rate, so `_exp_property_entries` finds nothing to walk
    and no price is applied — the mock replays the template's captured price whatever the
    scenario asked for. True with and without explicit pricing. Left as-is here because
    fixing it changes what every existing EXP scenario returns from price-check; if that is
    ever wired up, this test is the reminder to price it from the same numbers.
    """
    built = ScenarioEngine().build_expectations(_explicit_request())
    prebooking = next(
        item.expectation for item in built
        if item.supplier_code == "EXP" and item.log_type == "PreBooking"
    )
    template = json.loads(
        (TEMPLATES_DIR / "EXP" / "PreBooking" / "v1.json").read_text(encoding="utf-8")
    )
    assert _totals(prebooking)["inclusive"] == _totals(template)["inclusive"]


@needs_exp_templates
def test_without_explicit_pricing_the_mock_is_unchanged():
    """The whole point of the opt-in: absent the three fields, every byte is as before.

    Compares against a spec whose price equals the explicit total, so only the markup
    handling can differ — and it must, since the template's ratio no longer applies.
    """
    plain = ScenarioRequest(
        namespace="exp-explicit-pricing",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1043546",
        supplier_hotel_ids={"EXP": "2001358"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(
                    count=1, room_basis="RO", prices=[1120.0], refundable=[False]
                ),
            )
        ],
    )
    plain_totals = _totals(_get_exp_packages(ScenarioEngine().build_expectations(plain)))
    explicit_totals = _totals(_get_exp_packages(ScenarioEngine().build_expectations(_explicit_request())))

    assert plain_totals["inclusive"] == explicit_totals["inclusive"] == "1120.00"
    # Scaled off the template instead of set, so it is NOT the requested 120.
    assert plain_totals["marketing_fee"] != "120.00"
    # Everything the adapter does not read stays on the scaling path in both.
    for node in ("gross_profit", "property_inclusive"):
        if node in plain_totals:
            assert plain_totals[node] == explicit_totals[node], node


@needs_exp_templates
def test_explicit_pricing_syncs_the_get_order_mock():
    """A retrieved order has to match the package that was booked, so GetOrder follows the
    explicit total rather than the wizard's price entry."""
    request = _explicit_request("exp-explicit-booking")
    request.suppliers[0].packages.booking_package_index = 0
    built = ScenarioEngine().build_expectations(request)

    get_order = next(
        item.expectation for item in built
        if item.supplier_code == "EXP" and item.log_type == "GetOrder"
    )
    pricing = get_order["httpResponse"]["body"]["rooms"][0]["rate"]["pricing"]
    inclusive = pricing["totals"]["inclusive"]["billable_currency"]["value"]
    assert float(inclusive) == pytest.approx(1120.0, abs=0.02)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # Mistyped figure: 1000 + 100 is 1100, but the package price is 1120.
        ({"original_price_with_vat": [1000.0], "markup": [100.0]}, "must equal"),
        # One without the other: the split is only defined by both.
        ({"original_price_with_vat": [1000.0]}, "given together"),
        ({"markup": [120.0]}, "given together"),
        ({"original_price_with_vat": [1240.0], "markup": [-120.0]}, "negative"),
        # Ragged lists would silently price only some packages.
        (
            {"original_price_with_vat": [1000.0, 2000.0], "markup": [120.0]},
            "same length",
        ),
        # More splits than packages: the extra one could never be applied.
        (
            {"original_price_with_vat": [1000.0, 2000.0], "markup": [120.0, 240.0]},
            "only 1 price",
        ),
    ],
)
def test_explicit_pricing_rejects_inconsistent_input(kwargs, expected):
    """Rejected, never back-solved: a set that does not add up means a typo, and quietly
    recomputing it would mock a price nobody asked for."""
    with pytest.raises(ValueError, match=expected):
        PackageSpec(count=1, room_basis="RO", prices=[1120.0], refundable=[False], **kwargs)


def test_explicit_pricing_tolerates_two_decimal_rounding():
    """Money carries 2 decimals and floats do not add exactly, so the check has a 0.01
    tolerance — 1000.02 + 120.03 must not be rejected for failing to equal the 1120.05 price."""
    spec = PackageSpec(
        count=1,
        prices=[1120.05],
        original_price_with_vat=[1000.02],
        markup=[120.03],
    )
    assert spec.has_explicit_pricing


def test_a_spec_without_the_fields_is_not_explicit():
    assert not PackageSpec(count=1, prices=[100.0]).has_explicit_pricing
