"""Suppliers sharing hotels-derby-bts-adapter: CHC and HIL.

The interesting claim is attribution. Both suppliers log an identical ``source``, and a
single search SID contains rows from both, so ingest has to separate them by
``header.supplierId`` or it writes one supplier's payload into the other's templates.
"""

import pytest

from app.ingest.expectation_builder import payload_supplier_id
from app.ingest.template_ingestor import TemplateIngestor
from app.models.scenario import PackageSpec
from app.plugins import PLUGINS, DerbyBtsMockPlugin
from app.plugins.chc import ChcMockPlugin
from app.plugins.hil import HilMockPlugin

DERBY_SOURCE = "hotels-derby-bts-adapter"


def _derby_detail(supplier_id: str, room_id: str = "K1") -> dict:
    """A Derby availability log detail, shaped like templates/HIL/Packages/v1.json."""
    body = {
        "header": {"version": "v1.2", "supplierId": supplier_id, "distributorId": "ALTAYYAR"},
        "hotelId": "RUHSK",
        "stayRange": {"checkin": "2025-11-01", "checkout": "2025-11-02"},
        "roomCriteria": {"roomCount": 1, "adultCount": 2, "childCount": 0, "childAges": []},
        "roomRates": [
            {
                "roomId": room_id,
                "rateId": "OD30DV",
                "currency": "SAR",
                "amountBeforeTax": [686.7],
                "amountAfterTax": [829.19],
                "mealPlan": "HB",
                "cancelPolicy": {
                    "code": "1D1N_1N",
                    "cancelPenalties": [
                        {"noShow": False, "cancellable": True, "penaltyCharge": {"percent": 100}}
                    ],
                },
            }
        ],
    }
    return {
        "request": {"url": "https://derby.example.com/bts/api/availability", "body": body},
        "response": {"body": body},
    }


def _derby_expectation(supplier_id: str = "HILTON") -> dict:
    """The mock expectation shape a plugin mutates, as ingest would have written it."""
    return {
        "httpRequest": {"path": "/bts/api/availability", "method": "POST"},
        "httpResponse": {"statusCode": 200, "body": _derby_detail(supplier_id)["response"]["body"]},
    }


# ── registration + identity ─────────────────────────────────────────────────────


def test_both_derby_suppliers_are_registered():
    assert isinstance(PLUGINS["CHC"], DerbyBtsMockPlugin)
    assert isinstance(PLUGINS["HIL"], DerbyBtsMockPlugin)
    assert PLUGINS["HIL"].code == "HIL"
    assert PLUGINS["HIL"].payload_supplier_id == "HILTON"


def test_source_cannot_separate_them_but_payload_can():
    chc, hil = ChcMockPlugin(), HilMockPlugin()
    # Same adapter: source matching is deliberately identical.
    assert chc.matches_adapter_source(DERBY_SOURCE)
    assert hil.matches_adapter_source(DERBY_SOURCE)
    assert not hil.matches_adapter_source("hotels-rhk-adapter-service-staging")

    assert hil.claims_log_payload(_derby_detail("HILTON"))
    assert not hil.claims_log_payload(_derby_detail("CHOICE"))
    assert chc.claims_log_payload(_derby_detail("CHOICE"))
    assert not chc.claims_log_payload(_derby_detail("HILTON"))


def test_an_unidentifiable_row_is_refused_rather_than_guessed():
    """A row with no header can't be told from a sibling's, so nobody claims it."""
    headerless = {"response": {"body": {"roomRates": []}}}
    assert not HilMockPlugin().claims_log_payload(headerless)
    assert not ChcMockPlugin().claims_log_payload(headerless)


def test_payload_supplier_id_reads_request_when_response_has_no_header():
    detail = _derby_detail("HILTON")
    detail["response"] = {"body": {"roomRates": []}}
    assert payload_supplier_id(detail) == "HILTON"
    assert payload_supplier_id({}) is None


def test_search_is_attributed_from_availhotels_not_the_header():
    """Derby's multi-hotel Search has no supplierId in its header — it sits per hotel.

    Every other Derby call carries header.supplierId; miss this one and ingest silently
    drops the Search template for both CHC and HIL.
    """
    search = {
        "response": {
            "body": {
                # Exactly what templates/HIL/Search/v1.json carries: no supplierId here.
                "header": {"distributorId": "ALTAYYAR", "version": "v1.2", "token": "tok"},
                "stayRange": {"checkin": "2026-09-01", "checkout": "2026-09-03"},
                "availHotels": [{"hotelId": "GI-RUHSK", "supplierId": "HILTON",
                                 "availRoomRates": []}],
            }
        }
    }
    assert payload_supplier_id(search) == "HILTON"
    assert HilMockPlugin().claims_log_payload(search)
    assert not ChcMockPlugin().claims_log_payload(search)


def test_payload_supplier_id_parses_a_json_string_body():
    import json

    body = _derby_detail("CHOICE")["response"]["body"]
    assert payload_supplier_id({"response": {"body": json.dumps(body)}}) == "CHOICE"


# ── ingest attribution ──────────────────────────────────────────────────────────

LIST_JSON = {
    "details": [
        {"logType": "Packages", "source": DERBY_SOURCE, "logUrl": "logs/packages_choice.gz"},
        {"logType": "Packages", "source": DERBY_SOURCE, "logUrl": "logs/packages_hilton.gz"},
    ]
}

DETAIL_BY_URL = {
    "logs/packages_choice.gz": _derby_detail("CHOICE", room_id="CHOICE_ROOM"),
    "logs/packages_hilton.gz": _derby_detail("HILTON", room_id="HILTON_ROOM"),
}


async def _fetch_detail(log_url: str) -> dict:
    return DETAIL_BY_URL[log_url]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected_room"),
    [("HIL", "HILTON_ROOM"), ("CHC", "CHOICE_ROOM")],
)
async def test_ingest_picks_its_own_rows_out_of_a_shared_sid(tmp_path, code, expected_room):
    """The other Derby supplier's row is first in the list and must not win."""
    ingestor = TemplateIngestor(
        templates_dir=tmp_path / "templates", field_maps_dir=tmp_path / "field-maps"
    )
    written = await ingestor.ingest_from_list_json(code, "sid-1", LIST_JSON, _fetch_detail)
    assert written == 1

    import json

    template = json.loads(
        (tmp_path / "templates" / code / "Packages" / "v1.json").read_text(encoding="utf-8")
    )
    body = template["httpResponse"]["body"]
    assert body["header"]["supplierId"] == ("HILTON" if code == "HIL" else "CHOICE")
    assert body["roomRates"][0]["roomId"] == expected_room


@pytest.mark.asyncio
async def test_ingest_writes_nothing_when_the_sid_holds_only_the_sibling(tmp_path):
    only_choice = {"details": [LIST_JSON["details"][0]]}
    ingestor = TemplateIngestor(
        templates_dir=tmp_path / "templates", field_maps_dir=tmp_path / "field-maps"
    )
    assert await ingestor.ingest_from_list_json("HIL", "sid-1", only_choice, _fetch_detail) == 0


# ── mutation: the three things the generic mutator gets wrong for Derby ─────────


def test_hil_prices_stay_arrays_and_refundability_rides_the_policy_code():
    """RoomRate declares List<Double>, and getRefundability reads only cancelPolicy.code."""
    plugin = HilMockPlugin()
    spec = PackageSpec(
        count=2,
        room_basis=["BB", "HB"],
        prices=[500.0, 750.0],
        refundable=[True, False],
        supplier_currency="SAR",
    )
    result = plugin.mutate_packages(
        _derby_expectation(), spec, "RUHSK", "2026-09-01", "2026-09-03", "Packages"
    )
    rates = result["httpResponse"]["body"]["roomRates"]
    assert len(rates) == 2
    assert [r["amountBeforeTax"] for r in rates] == [[500.0], [750.0]]
    assert [r["amountAfterTax"] for r in rates] == [[500.0], [750.0]]
    assert [r["mealPlan"] for r in rates] == ["BB", "HB"]
    assert [r["currency"] for r in rates] == ["SAR", "SAR"]
    # AD0_0 is in the adapter's REFUNDABLE_CODE allowlist; AD100P_100P is not.
    assert [r["cancelPolicy"]["code"] for r in rates] == ["AD0_0", "AD100P_100P"]


def test_hil_board_falls_back_to_room_only_for_a_code_derby_would_not_accept():
    plugin = HilMockPlugin()
    spec = PackageSpec(count=1, room_basis=["XX"], prices=[100.0], refundable=[True])
    result = plugin.mutate_packages(
        _derby_expectation(), spec, "RUHSK", "2026-09-01", "2026-09-03", "Packages"
    )
    assert result["httpResponse"]["body"]["roomRates"][0]["mealPlan"] == "RO"


# ── occupancy ───────────────────────────────────────────────────────────────────
#
# SupplierUtils.isValidAvailability compares adultCount, childCount and childAges
# (the response must be a superset) for every requested RoomCriterion. roomCount is NOT
# compared. A mismatch drops the whole availability with zero results and no error, so
# these assertions are what stands between a working mock and a silent empty search.


def _search_expectation() -> dict:
    """Derby multi-hotel Search, with the 1-adult occupancy the HIL template captured."""
    return {
        "httpRequest": {"path": "/bts/api/shopping/multihotels", "method": "POST"},
        "httpResponse": {
            "statusCode": 200,
            "body": {
                "header": {"distributorId": "ALTAYYAR", "version": "v1.2", "token": "tok"},
                "stayRange": {"checkin": "2025-11-01", "checkout": "2025-11-02"},
                "availHotels": [
                    {
                        "hotelId": "GI-RUHSK",
                        "supplierId": "HILTON",
                        "availRoomRates": [
                            {
                                "roomId": "K1",
                                "rateId": "OD30DV",
                                "currency": "SAR",
                                "amountBeforeTax": [686.7],
                                "amountAfterTax": [829.19],
                                "mealPlan": "HB",
                                "roomCriteria": {
                                    "roomCount": 1,
                                    "adultCount": 1,
                                    "childCount": 0,
                                    "childAges": [],
                                },
                                "cancelPolicy": {"code": "1D1N_1N", "cancelPenalties": []},
                            }
                        ],
                    }
                ],
            },
        },
    }


def _mutate(expectation: dict, spec: PackageSpec, log_type: str) -> dict:
    return HilMockPlugin().mutate_packages(
        expectation, spec, "GI-RUHSK", "2026-09-01", "2026-09-03", log_type
    )


def _spec(**kw) -> PackageSpec:
    return PackageSpec(count=2, room_basis=["RO"], prices=[400.0], refundable=[True], **kw)


def test_search_rates_default_to_two_adults():
    """The default search is 2 adults; a 1-adult template would return nothing."""
    body = _mutate(_search_expectation(), _spec(), "Search")["httpResponse"]["body"]
    rates = body["availHotels"][0]["availRoomRates"]
    assert len(rates) == 2
    for rate in rates:
        assert rate["roomCriteria"] == {
            "roomCount": 1,
            "adultCount": 2,
            "childCount": 0,
            "childAges": [],
        }


@pytest.mark.parametrize("plugin", [ChcMockPlugin(), HilMockPlugin()], ids=["CHC", "HIL"])
def test_every_derby_supplier_defaults_to_two_adults(plugin):
    """CHC and HIL both search 2 adults, so neither replays the template's occupancy.

    CHC's Search template happens to have been captured at 2 adults and HIL's at 1;
    stamping makes both explicit so a future re-ingest cannot change the occupancy a
    scenario advertises.
    """
    result = plugin.mutate_packages(
        _search_expectation(), _spec(), "X1", "2026-09-01", "2026-09-03", "Search"
    )
    rates = result["httpResponse"]["body"]["availHotels"][0]["availRoomRates"]
    assert rates
    assert all(r["roomCriteria"]["adultCount"] == 2 for r in rates)
    assert all(r["roomCriteria"]["childCount"] == 0 for r in rates)


def test_child_ages_drive_child_count():
    body = _mutate(_search_expectation(), _spec(child_ages=[8, 11]), "Search")["httpResponse"]["body"]
    criteria = body["availHotels"][0]["availRoomRates"][0]["roomCriteria"]
    assert criteria["childCount"] == 2
    assert criteria["childAges"] == [8, 11]
    assert criteria["adultCount"] == 2


def test_packages_carries_occupancy_at_body_level_not_per_rate():
    """Availability keeps one roomCriteria block; its rates are plain RoomRate."""
    packages = _derby_expectation()
    packages["httpResponse"]["body"]["roomCriteria"] = {
        "roomCount": 1, "adultCount": 1, "childCount": 0, "childAges": [],
    }
    body = _mutate(packages, _spec(adults=3), "Packages")["httpResponse"]["body"]
    assert body["roomCriteria"]["adultCount"] == 3
    assert "roomCriteria" not in body["roomRates"][0]


def test_no_occupancy_block_is_invented_where_the_payload_has_none():
    """Absent roomCriteria means the adapter reads none there — don't add one."""
    packages = _derby_expectation()
    packages["httpResponse"]["body"].pop("roomCriteria", None)
    body = _mutate(packages, _spec(), "Packages")["httpResponse"]["body"]
    assert "roomCriteria" not in body
    assert all("roomCriteria" not in r for r in body["roomRates"])


# ── mock paths ──────────────────────────────────────────────────────────────────


def test_derby_mock_paths_are_namespaced_and_never_collide(api_client):
    """MockServer matches on path + method only.

    Choice's Packages and PreBooking are both availability calls and were captured on the
    same path, so without distinct suffixes one expectation shadows the other. And without
    the /{namespace}/ prefix every Derby scenario registers identical paths, so two live
    scenarios answer each other's calls. Both are silent failures, hence this test.

    Takes ``api_client`` for the seeded supplier table: path rewriting reads the
    supplier's mock_config, and an unconfigured code silently falls back to no rewrite.
    """
    from app.core.mock_urls import build_mock_opt_urls, extract_paths_from_built
    from app.core.scenario_engine import ScenarioEngine
    from app.models.scenario import ScenarioRequest, SupplierScenario

    namespace = "qa-derby-paths"
    spec = PackageSpec(count=2, room_basis=["RO"], prices=[300.0, 400.0], refundable=[True, False])
    request = ScenarioRequest(
        namespace=namespace,
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"CHC": "GB999"},
        suppliers=[SupplierScenario(code="CHC", packages=spec)],
    )
    built = ScenarioEngine().build_expectations(request)
    paths = extract_paths_from_built(built)["CHC"]

    assert paths, "no expectations built"
    for log_type, path in paths.items():
        assert path.startswith(f"/{namespace}/"), f"{log_type} is not isolated: {path}"
    assert len(set(paths.values())) == len(paths), f"paths collide: {paths}"
    assert paths["Packages"] != paths["PreBooking"]

    # The contract has to point at the same paths, or the adapter calls an unmocked URL.
    opt = build_mock_opt_urls("http://mock", paths, "CHC")
    assert opt["availabilityUrl"] == f"http://mock{paths['Packages']}"
    assert opt["prebookingUrl"] == f"http://mock{paths['PreBooking']}"
    assert opt["searchUrl"] == f"http://mock{paths['Search']}"

