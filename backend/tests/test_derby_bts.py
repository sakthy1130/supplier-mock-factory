"""Suppliers sharing hotels-derby-bts-adapter: CHC and HIL.

The interesting claim is attribution. Both suppliers log an identical ``source``, and a
single search SID contains rows from both, so ingest has to separate them by
``header.supplierId`` or it writes one supplier's payload into the other's templates.
"""

import asyncio

import pytest

from app.env_context import use_env
from app.ingest.expectation_builder import payload_supplier_id
from app.ingest.template_ingestor import TemplateIngestor
from app.models.scenario import PackageSpec
from app.plugins import PLUGINS, DerbyBtsMockPlugin
from app.plugins.chc import ChcMockPlugin
from app.plugins.hil import HilMockPlugin
from app.services import supplier_service

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
                        {
                            "noShow": False,
                            "cancellable": True,
                            "cancelDeadline": {
                                "offsetTimeDropType": "BeforeArrival",
                                "offsetTimeUnit": "D",
                                "offsetTimeValue": 1,
                            },
                            "penaltyCharge": {"chargeBase": "NightBase", "nights": 1, "percent": 100},
                        }
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
                                "cancelPolicy": {
                                    "code": "5D1N_1N",
                                    "cancelPenalties": [
                                        {
                                            "noShow": False,
                                            "cancellable": True,
                                            "cancelDeadline": {
                                                "offsetTimeDropType": "BeforeArrival",
                                                "offsetTimeUnit": "D",
                                                "offsetTimeValue": 5,
                                            },
                                            # The real template stores this as a string.
                                            "penaltyCharge": {
                                                "chargeBase": "NightBase",
                                                "nights": "1",
                                                "percent": 100,
                                            },
                                        }
                                    ],
                                },
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
    kw.setdefault("count", 2)
    kw.setdefault("refundable", [True])
    return PackageSpec(room_basis=["RO"], prices=[400.0], **kw)


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


# ── hotel id prefix ─────────────────────────────────────────────────────────────


def test_hilton_replies_with_the_stripped_hotel_id(api_client):
    """Mapping hands out GI-RUHSK; the adapter calls Derby with RUHSK.

    Echoing the prefixed id back describes a hotel the supplier was never asked about,
    and the adapter's per-hotel lookups (room names among them) miss — zero packages,
    no error. Takes api_client because the flag lives on the seeded supplier row.
    """
    # HIL is seeded for stg only, and the flag is read from its row — in dev there is
    # no HIL config and nothing is stripped.
    with use_env("stg"):
        supplier_service.invalidate_cache()
        result = HilMockPlugin().mutate_packages(
            _derby_expectation(), _spec(), "GI-RUHSK", "2026-09-01", "2026-09-03", "Packages"
        )
    assert result["httpResponse"]["body"]["hotelId"] == "RUHSK"


def test_choice_keeps_its_hotel_id_untouched(api_client):
    """The flag is per supplier: Choice's ids are not prefixed, so nothing is stripped."""
    result = ChcMockPlugin().mutate_packages(
        _derby_expectation("CHOICE"), _spec(), "GB-113", "2026-09-01", "2026-09-03", "Packages"
    )
    assert result["httpResponse"]["body"]["hotelId"] == "GB-113"


def test_an_unprefixed_id_is_left_alone(api_client):
    """Nothing to strip — a bare code must survive verbatim, not lose its first char."""
    with use_env("stg"):
        supplier_service.invalidate_cache()
        result = HilMockPlugin().mutate_packages(
            _derby_expectation(), _spec(), "RUHSK", "2026-09-01", "2026-09-03", "Packages"
        )
    assert result["httpResponse"]["body"]["hotelId"] == "RUHSK"


def test_search_and_packages_describe_the_same_cancel_policy():
    """The two templates come from different sessions and disagree on the deadline.

    Nothing in the adapter compares the two — rate identity is rateId-roomId-
    refundability — but a mock that advertises one policy in search and another in
    availability is wrong on its own terms, and it is the kind of drift that gets
    blamed for a silent zero-package result.
    """
    spec = _spec(count=2, refundable=[True, True])
    search = HilMockPlugin().mutate_packages(
        _search_expectation(), spec, "DXBAS", "2026-09-01", "2026-09-03", "Search"
    )
    packages = HilMockPlugin().mutate_packages(
        _derby_expectation(), spec, "DXBAS", "2026-09-01", "2026-09-03", "Packages"
    )

    def policy(rate: dict) -> dict:
        cp = rate["cancelPolicy"]
        return {"code": cp["code"], "penalties": cp["cancelPenalties"]}

    s_rate = search["httpResponse"]["body"]["availHotels"][0]["availRoomRates"][0]
    p_rate = packages["httpResponse"]["body"]["roomRates"][0]
    assert policy(s_rate) == policy(p_rate)
    # nights is numeric on both sides — one template stored it as a string.
    assert isinstance(p_rate["cancelPolicy"]["cancelPenalties"][0]["penaltyCharge"]["nights"], int)


def test_ingest_keeps_search_on_the_packages_hotel():
    """Derby chunks search one hotel per call, so a SID holds a Search row per hotel.

    Taking whichever came first gives a Search template for one hotel and a Packages
    template for another, whose room ids have nothing in common — and the packages
    transform keeps only rates whose roomId belongs to the hotel, so every rate is
    filtered and the scenario returns zero packages with no error.
    """
    import json as _json

    from app.ingest.template_ingestor import TemplateIngestor

    def search_detail(hotel: str, room: str) -> dict:
        body = {
            "header": {"version": "v1.2", "distributorId": "ALTAYYAR"},
            "stayRange": {"checkin": "2026-09-01", "checkout": "2026-09-03"},
            "availHotels": [
                {
                    "hotelId": hotel,
                    "supplierId": "HILTON",
                    "availRoomRates": [
                        {"roomId": room, "rateId": "R1", "currency": "USD",
                         "amountBeforeTax": [100.0], "amountAfterTax": [100.0],
                         "mealPlan": "RO",
                         "roomCriteria": {"roomCount": 1, "adultCount": 2,
                                          "childCount": 0, "childAges": []},
                         "cancelPolicy": {"code": "1D1N_1N", "cancelPenalties": []}}
                    ],
                }
            ],
        }
        return {"request": {"url": "https://d/bts/api/shopping/multihotels", "body": body},
                "response": {"body": body}}

    listing = {"details": [
        # The wrong hotel's row comes first, exactly as it did in the real SID.
        {"logType": "Search", "source": DERBY_SOURCE, "logUrl": "logs/search_other.gz"},
        {"logType": "Search", "source": DERBY_SOURCE, "logUrl": "logs/search_target.gz"},
        {"logType": "Packages", "source": DERBY_SOURCE, "logUrl": "logs/packages.gz"},
    ]}
    details = {
        "logs/search_other.gz": search_detail("DXBAL", "NKRR"),
        "logs/search_target.gz": search_detail("DXBAS", "K3RRF2"),
        "logs/packages.gz": _derby_detail("HILTON", room_id="K3RRF2"),
    }
    details["logs/packages.gz"]["response"]["body"]["hotelId"] = "DXBAS"
    details["logs/packages.gz"]["request"]["body"]["hotelId"] = "DXBAS"

    async def fetch(log_url: str) -> dict:
        return details[log_url]

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        written = asyncio.run(
            TemplateIngestor(templates_dir=root / "t", field_maps_dir=root / "f")
            .ingest_from_list_json("HIL", "sid-1", listing, fetch)
        )
        assert written == 2
        search = _json.loads((root / "t" / "HIL" / "Search" / "v1.json").read_text())
        hotel = search["httpResponse"]["body"]["availHotels"][0]
        assert hotel["hotelId"] == "DXBAS", "Search must follow the Packages hotel"
        assert hotel["availRoomRates"][0]["roomId"] == "K3RRF2"


# ── contract permissions ────────────────────────────────────────────────────────


def _config_with(forced: dict):
    from app.models.supplier import MockConfig, MutationConfig, SupplierConfig

    return SupplierConfig(
        id="x", code="HIL", env="stg", name="Hilton",
        mock_config=MockConfig(forced_permission=forced),
        mutation_config=MutationConfig(),
        log_types=["Search"],
    )


def test_forced_permission_flips_can_book_keeping_the_contract_s_own_shape():
    """Hilton's reference is the safe "dont-book" contract, so a clone inherits
    canBook false and the booking flow is refused before the mock is consulted.

    Backoffice returns these flags as the strings "true"/"false" on a real contract, so
    the override has to write a string back — a raw bool risks the block being misread.
    """
    from app.core.contract_provisioner import _apply_forced_permission

    body = {
        "permission": {
            "isEnable": "true", "canSearch": "true", "canBook": "false",
            "canCancel": "true", "canPackages": "true", "canOrder": "true",
        }
    }
    _apply_forced_permission(body, _config_with({"canBook": True}))
    assert body["permission"]["canBook"] == "true"
    # Nothing else is touched.
    assert body["permission"]["canSearch"] == "true"
    assert body["permission"]["canPackages"] == "true"
    assert body["permission"]["canOrder"] == "true"


def test_forced_permission_writes_a_bool_when_the_body_uses_bools():
    from app.core.contract_provisioner import _apply_forced_permission

    body = {"permission": {"canBook": False, "canSearch": True}}
    _apply_forced_permission(body, _config_with({"canBook": True}))
    assert body["permission"]["canBook"] is True


def test_a_supplier_with_no_forced_permission_is_left_alone():
    from app.core.contract_provisioner import _apply_forced_permission

    body = {"permission": {"canBook": "false"}}
    _apply_forced_permission(body, _config_with({}))
    assert body["permission"]["canBook"] == "false"



# ── ingest: a logged failure must not become the template ───────────────────────


def _derby_get_order_detail(supplier_id: str = "HILTON") -> dict:
    """A successful reservation-detail log, shaped like templates/HIL/GetOrder/v1.json."""
    header = {"version": "v1.2", "supplierId": supplier_id, "distributorId": "ALTAYYAR"}
    return {
        "request": {
            "url": "https://derby.example.com/bts/api/reservation/detail",
            "body": {"header": header, "reservationIds": {"derbyResId": "GP721114932T8E491E91J"}},
        },
        "response": {
            "body": {
                "header": header,
                "reservations": [
                    {
                        "status": "Confirmed",
                        "hotelId": "DXBAS",
                        "reservationIds": {"derbyResId": "GP721114932T8E491E91J"},
                        "roomRates": [{"roomId": "K1D", "rateId": "OD25DN", "mealPlan": "HB"}],
                    }
                ],
            }
        },
    }


def _derby_failed_get_order_detail(supplier_id: str = "HILTON") -> dict:
    """What the log holds when the supplier call itself failed: the outbound request is
    intact (so attribution still claims the row) but the response is Enigma's error
    envelope, with the upstream status and an empty body."""
    detail = _derby_get_order_detail(supplier_id)
    detail["response"] = {
        "exception": "com.fasterxml.jackson.databind.exc.MismatchedInputException: "
        "No content to map due to end-of-input",
        "headers": {"content-length": ["0"]},
        "body": "",
        "httpStatusCode": 404,
    }
    return detail


@pytest.mark.asyncio
async def test_ingest_skips_a_failed_get_order_row_for_the_next_candidate(tmp_path):
    """The newest GetOrder row wins normally — but not when it logged a failed call."""
    import json

    list_json = {
        "details": [
            {
                "logType": "GetOrder",
                "source": DERBY_SOURCE,
                "logUrl": "logs/get_order_ok.gz",
                "timestamp": "2026-02-20T15:00:00Z",
            },
            {
                "logType": "GetOrder",
                "source": DERBY_SOURCE,
                "logUrl": "logs/get_order_failed.gz",
                "timestamp": "2026-02-20T15:09:31Z",
            },
        ]
    }
    details = {
        "logs/get_order_ok.gz": _derby_get_order_detail(),
        "logs/get_order_failed.gz": _derby_failed_get_order_detail(),
    }

    async def fetch(log_url: str) -> dict:
        return details[log_url]

    ingestor = TemplateIngestor(
        templates_dir=tmp_path / "templates", field_maps_dir=tmp_path / "field-maps"
    )
    assert await ingestor.ingest_from_list_json("HIL", "sid-1", list_json, fetch) == 1

    body = json.loads(
        (tmp_path / "templates" / "HIL" / "GetOrder" / "v1.json").read_text(encoding="utf-8")
    )["httpResponse"]["body"]
    assert "exception" not in body
    assert body["reservations"][0]["status"] == "Confirmed"


@pytest.mark.asyncio
async def test_ingest_writes_no_template_when_every_row_logged_a_failure(tmp_path):
    """No template beats a poison one: the log type is reported missing and dumped to
    _diagnostics instead of becoming a mock that answers 200 with a stack trace."""
    list_json = {
        "details": [
            {
                "logType": "GetOrder",
                "source": DERBY_SOURCE,
                "logUrl": "logs/get_order_failed.gz",
                "timestamp": "2026-02-20T15:09:31Z",
            }
        ]
    }

    async def fetch(log_url: str) -> dict:
        return _derby_failed_get_order_detail()

    ingestor = TemplateIngestor(
        templates_dir=tmp_path / "templates", field_maps_dir=tmp_path / "field-maps"
    )
    result = await ingestor._ingest_supplier(
        HilMockPlugin(), "sid-1", list_json["details"], fetch_detail=fetch
    )

    assert "GetOrder" in result.missing
    assert not (tmp_path / "templates" / "HIL" / "GetOrder" / "v1.json").exists()
    assert list((tmp_path / "templates" / "HIL" / "_diagnostics").glob("*.json"))


# ── booking-flow ids ────────────────────────────────────────────────────────────


def test_hil_booking_flow_mocks_all_describe_the_same_reservation(api_client):
    """Booking, GetOrder and CancelOrder must carry one reservation id after injection.

    Derby keeps the ids at body level in Booking/CancelOrder but nested under
    ``reservations[0]`` in GetOrder, so the field map has to list both — it is generated
    from the templates, and while HIL's GetOrder template was a captured failure it
    contained no ids at all, leaving GetOrder pointing at the template's stale ones while
    Booking got the fresh id. The adapter then reports an order for a reservation nobody
    booked. Takes api_client for the seeded HIL row.
    """
    import json
    import pathlib

    from app.core.booking_id_injector import BookingIdInjector
    from app.core.scenario_engine import ScenarioEngine
    from app.models.scenario import ScenarioRequest, SupplierScenario

    spec = PackageSpec(
        count=2,
        room_basis=["BB", "HB"],
        prices=[500.0, 750.0],
        refundable=[True, False],
        supplier_currency="SAR",
        booking_package_index=0,
    )
    request = ScenarioRequest(
        namespace="qa-derby-ids",
        check_in="2026-09-10",
        check_out="2026-09-12",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"HIL": "HL-DXBAS"},
        suppliers=[SupplierScenario(code="HIL", packages=spec, contract_currency="USD")],
    )
    field_map = json.loads(
        (pathlib.Path(__file__).resolve().parents[2] / "field-maps" / "HIL.json").read_text()
    )

    with use_env("stg"):
        supplier_service.invalidate_cache()
        by_type = {
            item.log_type: item.expectation
            for item in ScenarioEngine().build_expectations(request)
        }
        new_id = BookingIdInjector().inject(by_type, "HIL", field_map)

    booking_ids = by_type["Booking"]["httpResponse"]["body"]["reservationIds"]
    cancel_ids = by_type["CancelOrder"]["httpResponse"]["body"]["reservationIds"]
    reservation = by_type["GetOrder"]["httpResponse"]["body"]["reservations"][0]

    assert set(booking_ids.values()) == {new_id}
    assert set(cancel_ids.values()) == {new_id}
    assert set(reservation["reservationIds"].values()) == {new_id}
    # The order has to read back as confirmed for the booked dates, or booking-service
    # rejects it however well the ids line up.
    assert reservation["status"] == "Confirmed"
    assert reservation["stayRange"] == {"checkin": "2026-09-10", "checkout": "2026-09-12"}


def test_odis_hil_forces_bts_adapter_without_losing_other_mock_config():
    """ODIS's reference contract picks the wrong Derby adapter; SMF has to force it back.

    "mock-hil" carries isBTS false, which routes HIL to hotels-derby-adapter (protocol
    v3.1, sends the mapping id unstripped) instead of hotels-derby-bts-adapter (v1.2,
    strips to the bare code) that SMF's templates were captured against. The mismatch is
    silent — search reports COMPLETED_SUCCESSFULLY with totalResults 0 — so only the
    later /packages 404 is visible, which blames the hotel rather than the adapter.
    """
    import copy

    from app.db.seed_suppliers import SEED_SUPPLIERS, _spec_for_env

    hil = [s for s in SEED_SUPPLIERS if s["code"] == "HIL"][0]
    base = copy.deepcopy(hil["mock_config"])

    odis = _spec_for_env(hil, "odis")["mock_config"]
    assert odis["forced_opt"] == {"isBTS": True, "enableAdapterTransformedLog": True}

    # The override merges INTO mock_config. A shallow {**spec, **override} would drop
    # every key it does not restate, silently un-stripping hotel ids and re-inheriting
    # the reference contract's canBook false.
    assert odis["strip_hotel_id_prefix"] is True
    assert odis["forced_permission"] == {"canBook": True}
    assert odis["mock_path_suffix"] == base["mock_path_suffix"]

    # Staging keeps isBTS from its own reference contract and must not be touched.
    assert _spec_for_env(hil, "stg")["mock_config"] == base
    assert hil["mock_config"] == base, "the shared spec dict must not be mutated"


def test_hil_defaults_the_separate_availability_timeout():
    """The adapter reads a SEPARATE timeout for availability; blank means 0, not "unset".

    HIL had no opt_defaults at all, so a reference contract carrying
    availabilityTimeoutSeconds "" left the adapter with 0 and it abandoned the packages
    call before the request left the process — nothing reached MockServer, the adapter
    logged a null response, and /packages returned an empty list with a
    COMPLETED_SUCCESSFULLY status and no error. Search was unaffected because it uses the
    contract's own timeoutSeconds, so the scenario looked half-working. CHC, which shares
    the adapter, has always defaulted this.
    """
    from app.core.contract_opt import apply_contract_opt_defaults
    from app.db.seed_suppliers import SEED_SUPPLIERS, _spec_for_env
    from app.models.supplier import MockConfig

    hil = [s for s in SEED_SUPPLIERS if s["code"] == "HIL"][0]
    assert hil["mock_config"]["opt_defaults"]["availabilityTimeoutSeconds"] == "30"

    for env in ("stg", "odis"):
        config = MockConfig(**_spec_for_env(hil, env)["mock_config"])
        # "" and "0" are the two shapes a reference contract actually carries.
        for blank in ("", "0", None):
            opt = apply_contract_opt_defaults(
                {"availabilityTimeoutSeconds": blank}, config, "http://mock"
            )
            assert opt["availabilityTimeoutSeconds"] == "30", (env, blank)
        # A real configured timeout is left alone.
        opt = apply_contract_opt_defaults(
            {"availabilityTimeoutSeconds": "12"}, config, "http://mock"
        )
        assert opt["availabilityTimeoutSeconds"] == "12"
