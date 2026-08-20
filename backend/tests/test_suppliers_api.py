"""Supplier configuration: seeding, CRUD, readiness, and the generic mutator.

The point of these is the end-to-end claim behind the Suppliers screen: a supplier
added with nothing but an API call can build a full set of expectations.
"""

import json
import shutil
from pathlib import Path

import pytest

from app.core.scenario_engine import ScenarioEngine
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierScenario
from app.plugins import GenericMockPlugin, resolve_plugin

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "templates"

DEV = {"X-SMF-Env": "dev"}
STG = {"X-SMF-Env": "stg"}

NEW_SUPPLIER = {
    "code": "tst",  # lower case on purpose — the API normalizes it
    "name": "Test Supplier",
    "supplier_type": "net",
    "supplier_id": "6600000000000000000000aa",
    "auto_id": 109999,
    "default_supplier_currency": "eur",
    "default_contract_currency": "usd",
    "log_types": ["Search", "Packages", "Booking", "GetOrder", "CancelOrder"],
    "package_log_types": ["Search", "Packages"],
    "ui_color": "#6b7a3f",
    "mock_config": {
        "canonical_base": {
            "Search": "/tst/api/v1/distribution",
            "Packages": "/tst/api/v1/distribution",
            "Booking": "/tst/api/v1/accommodation",
            "GetOrder": "/tst/api/v1/accommodation",
            "CancelOrder": "/tst/api/v1/accommodation",
        },
        "mock_path_suffix": {
            "Search": "search",
            "Packages": "details",
            "Booking": "confirm",
            "GetOrder": "search",
            "CancelOrder": "cancel",
        },
        "opt_field_map": {
            "Search": "searchUrl",
            "Packages": "availabilityUrl",
            "Booking": "bookingUrl",
            "GetOrder": "orderUrl",
            "CancelOrder": "cancelBookingUrl",
        },
        "path_rewrite": True,
        "set_mock_server_url": True,
        "dynamic_market_type": "DynamicMarkupTarget",
    },
    # EXT's payload shape, since that's whose templates the fixture copies.
    "mutation_config": {
        "packages_path": "httpResponse.body.body.0.accommodations",
        "check_in_keys": ["checkInDate"],
        "check_out_keys": ["checkOutDate"],
        "price_keys": ["totalPrice", "netPrice", "initialPrice"],
        "board_key": "board",
        "room_name_key": "roomName",
        "currency_key": "currency",
        "package_id_key": "id",
        "hotel_id_key": "hotelId",
        "board_values": ["RO", "BB", "HB", "FB", "AI"],
        "adapter_source_match": "tstadapter",
    },
}


@pytest.fixture
def tst_templates():
    """Give TST a template set by copying EXT's, and clean up afterwards."""
    target = TEMPLATES_DIR / "TST"
    for log_type in NEW_SUPPLIER["log_types"]:
        destination = target / log_type / "v1.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(TEMPLATES_DIR / "EXT" / log_type / "v1.json", destination)
    yield target
    shutil.rmtree(target, ignore_errors=True)


# ── Seeding ────────────────────────────────────────────────────────────────────


def test_seed_creates_built_in_suppliers_per_env(api_client):
    dev = {s["code"] for s in api_client.get("/api/suppliers", headers=DEV).json()}
    stg = {s["code"] for s in api_client.get("/api/suppliers", headers=STG).json()}
    assert dev == stg == {"HBS", "EXP", "RHK", "CHC", "EXT"}


def test_seed_keeps_dev_and_stg_backoffice_ids_separate(api_client):
    """Dev must not inherit stg's supplier _id — that NPEs hotel-connectivity-core."""
    dev = api_client.get("/api/suppliers/HBS", headers=DEV).json()
    stg = api_client.get("/api/suppliers/HBS", headers=STG).json()
    assert dev["supplier_id"] == "60059008536a5c532c0936a2"
    assert dev["auto_id"] == 100006
    assert stg["supplier_id"] == "5fd5fefb1a4e866f7b3cea44"
    assert stg["auto_id"] == 100004


def test_seed_preserves_per_supplier_behaviour_flags(api_client):
    hbs = api_client.get("/api/suppliers/HBS", headers=STG).json()
    exp = api_client.get("/api/suppliers/EXP", headers=STG).json()
    rhk = api_client.get("/api/suppliers/RHK", headers=STG).json()
    chc = api_client.get("/api/suppliers/CHC", headers=STG).json()

    # HBS builds opt URLs from canonical paths and rewrites mock paths.
    assert hbs["mock_config"]["opt_source"] == "canonical"
    assert hbs["mock_config"]["path_rewrite"] is True
    assert hbs["mock_config"]["dynamic_market_type"] == "DynamicMarkupTarget"
    # EXP namespaces its Search/Packages paths and is the market price source.
    assert exp["mock_config"]["path_namespaced"] is True
    assert exp["mock_config"]["unwrap_adapter_log_body"] is True
    assert exp["mock_config"]["dynamic_market_type"] == "MarketPriceSource"
    assert exp["mock_config"]["forced_opt"] == {"enableGenericBedding": False}
    # RHK was never given a dynamicMarketType — it keeps the reference contract's.
    assert rhk["mock_config"]["dynamic_market_type"] is None
    # CHC mutates packages on more than Search/Packages.
    assert set(chc["package_log_types"]) == {"Search", "Packages", "PreBooking", "GetOrder"}


def test_seed_is_idempotent(api_client):
    from app.db.database import get_session_factory
    from app.db.seed_suppliers import seed_suppliers

    assert seed_suppliers(get_session_factory()) == 0


# ── CRUD ───────────────────────────────────────────────────────────────────────


def test_create_supplier_normalizes_code_and_currencies(api_client):
    response = api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "TST"
    assert body["default_supplier_currency"] == "EUR"
    assert body["default_contract_currency"] == "USD"
    assert body["env"] == "dev"


def test_create_supplier_is_scoped_to_one_env(api_client):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    assert api_client.get("/api/suppliers/TST", headers=DEV).status_code == 200
    assert api_client.get("/api/suppliers/TST", headers=STG).status_code == 404


def test_create_duplicate_supplier_conflicts(api_client):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    duplicate = api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    assert duplicate.status_code == 409


def test_create_supplier_rejects_unknown_log_type(api_client):
    payload = {**NEW_SUPPLIER, "log_types": ["Search", "Nonsense"]}
    assert api_client.post("/api/suppliers", json=payload, headers=DEV).status_code == 422


def test_package_log_types_cannot_exceed_served_log_types(api_client):
    payload = {
        **NEW_SUPPLIER,
        "log_types": ["Search", "Packages"],
        # PreBooking isn't served, so it can't be mutated either.
        "package_log_types": ["Search", "Packages", "PreBooking"],
    }
    body = api_client.post("/api/suppliers", json=payload, headers=DEV).json()
    assert body["package_log_types"] == ["Search", "Packages"]


def test_update_supplier_takes_effect_on_the_next_build(api_client):
    """A UI edit has to be visible immediately, not after a restart."""
    from app.services.supplier_service import get_supplier_config

    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    assert get_supplier_config("TST", "dev").name == "Test Supplier"

    api_client.put(
        "/api/suppliers/TST", json={**NEW_SUPPLIER, "name": "Renamed"}, headers=DEV
    )
    assert get_supplier_config("TST", "dev").name == "Renamed"


def test_supplier_code_cannot_be_renamed(api_client):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    response = api_client.put(
        "/api/suppliers/TST", json={**NEW_SUPPLIER, "code": "OTH"}, headers=DEV
    )
    assert response.status_code == 400


def test_delete_supplier(api_client):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    assert api_client.delete("/api/suppliers/TST", headers=DEV).status_code == 204
    assert api_client.get("/api/suppliers/TST", headers=DEV).status_code == 404


def test_delete_supplier_blocked_while_a_scenario_uses_it(api_client):
    """Deleting it would orphan the scenario's expectations and contracts."""
    import uuid

    from app.db.database import get_session_factory
    from app.db.models import ScenarioRecord

    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    with get_session_factory()() as session:
        session.add(
            ScenarioRecord(
                id=str(uuid.uuid4()),
                namespace="uses-tst",
                status="READY",
                env="dev",
                request_json={},
                contracts_json={},
                booking_ids_json={},
                suppliers_json=["TST"],
                check_in="2026-09-01",
                check_out="2026-09-03",
                hotel_id="1446194",
            )
        )
        session.commit()

    response = api_client.delete("/api/suppliers/TST", headers=DEV)
    assert response.status_code == 409
    assert "uses-tst" in response.json()["detail"]


# ── Readiness ──────────────────────────────────────────────────────────────────


def test_readiness_reports_missing_templates(api_client):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    checks = {
        c["key"]: c for c in api_client.get("/api/suppliers/TST/readiness", headers=DEV).json()["checks"]
    }
    assert checks["templates"]["ok"] is False
    assert "Search" in checks["templates"]["detail"]


def test_readiness_ok_once_templates_exist(api_client, tst_templates):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    readiness = api_client.get("/api/suppliers/TST/readiness", headers=DEV).json()
    assert readiness["ready"] is True
    checks = {c["key"]: c for c in readiness["checks"]}
    # No hand-written plugin, but that never blocks — the generic mutator covers it.
    assert checks["plugin"]["ok"] is False
    assert checks["plugin"]["blocking"] is False


def test_readiness_flags_a_missing_packages_path(api_client, tst_templates):
    payload = {**NEW_SUPPLIER, "mutation_config": {**NEW_SUPPLIER["mutation_config"], "packages_path": ""}}
    api_client.post("/api/suppliers", json=payload, headers=DEV)
    readiness = api_client.get("/api/suppliers/TST/readiness", headers=DEV).json()
    assert readiness["ready"] is False
    assert "packages path" in {c["key"]: c["detail"] for c in readiness["checks"]}["mutation"]


# ── The end-to-end claim ───────────────────────────────────────────────────────


def test_new_supplier_uses_the_generic_plugin(api_client):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    from app.env_context import set_current_env

    set_current_env("dev")
    plugin = resolve_plugin("TST")
    assert isinstance(plugin, GenericMockPlugin)
    assert plugin.matches_adapter_source("hotels-tstadapter-search")
    assert not plugin.matches_adapter_source("hotels-extranet-search")


def test_built_in_supplier_keeps_its_hand_written_plugin():
    from app.plugins import HbsMockPlugin

    assert isinstance(resolve_plugin("HBS"), HbsMockPlugin)


def test_probe_builds_every_log_type_for_a_new_supplier(api_client, tst_templates):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    probe = api_client.post("/api/suppliers/TST/probe", headers=DEV).json()
    assert probe["ok"] is True
    assert probe["plugin"] == "generic"
    assert {r["log_type"] for r in probe["log_types"]} == set(NEW_SUPPLIER["log_types"])
    paths = {r["log_type"]: r["path"] for r in probe["log_types"]}
    # path_rewrite pins each log type onto canonical base + suffix.
    assert paths["Search"] == "/tst/api/v1/distribution/search"
    assert paths["Packages"] == "/tst/api/v1/distribution/details"
    assert paths["CancelOrder"] == "/tst/api/v1/accommodation/cancel"


def test_probe_reports_the_failure_instead_of_raising(api_client):
    """No templates on disk — the screen needs the reason, not a 500."""
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    probe = api_client.post("/api/suppliers/TST/probe", headers=DEV).json()
    assert probe["ok"] is False
    assert probe["error"] == "FileNotFoundError: Templates not found for supplier TST"


def test_generic_mutation_produces_the_requested_packages(api_client, tst_templates):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    from app.env_context import set_current_env

    set_current_env("dev")

    request = ScenarioRequest(
        namespace="tst-generic",
        check_in="2026-10-05",
        check_out="2026-10-08",
        atg_hotel_id="1446194",
        suppliers=[
            SupplierScenario(
                code="TST",
                contract_currency="USD",
                packages=PackageSpec(
                    count=3,
                    # Only two prices for three packages, and one invalid board.
                    room_basis=["RO", "BB", "XX"],
                    room_names=["Alpha", "Beta", "Gamma"],
                    supplier_currency="SAR",
                    prices=[111.0, 222.0],
                    refundable=[True, False],
                ),
            )
        ],
    )
    built = ScenarioEngine().build_expectations(request)
    packages = next(b for b in built if b.log_type == "Packages")
    hotel = packages.expectation["httpResponse"]["body"]["body"][0]

    assert hotel["hotelId"] == "1446194"
    accommodations = hotel["accommodations"]
    assert len(accommodations) == 3

    prices = [a["totalPrice"] for a in accommodations]
    assert prices == [111.0, 222.0, 222.0], "a short price list pads with its last value"

    boards = [a["distributions"][0]["board"] for a in accommodations]
    assert boards == ["RO", "BB", "RO"], "an unsupported board falls back to the first allowed"

    assert [a["distributions"][0]["roomName"] for a in accommodations] == ["Alpha", "Beta", "Gamma"]
    assert {a["currency"] for a in accommodations} == {"SAR"}
    assert all(a["checkInDate"] == "2026-10-05" for a in accommodations)
    ids = [a["id"] for a in accommodations]
    assert len(set(ids)) == 3, "each package needs its own id or the adapter merges them"


def test_unconfigured_supplier_fails_with_an_actionable_message():
    from app.services.supplier_service import UnknownSupplierError

    with pytest.raises(UnknownSupplierError, match="Suppliers screen"):
        resolve_plugin("ZZZ")


# ── Building templates from a SID ──────────────────────────────────────────────

# One log row per log type, sourced from a "tstadapter" service so it matches the
# NEW_SUPPLIER config's adapter_source_match.
_TST_LIST_JSON = {
    "details": [
        {
            "logType": log_type,
            "source": "hotel-connectivity-tstadapter-service",
            "logUrl": f"logs/sid/{log_type}_TST.json.gz",
        }
        for log_type in ("Search", "Packages", "Booking")
    ]
    + [
        # A different supplier's rows in the same SID must be ignored.
        {
            "logType": "Search",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/Search_HBS.json.gz",
        }
    ]
}

_TST_DETAILS = {
    f"logs/sid/{log_type}_TST.json.gz": {
        "request": {
            "method": "POST",
            "url": f"https://tst.example.com/api/v2/{log_type.lower()}",
            "body": {"checkInDate": "2026-08-01", "checkOutDate": "2026-08-03"},
        },
        "response": {
            "body": {
                "body": [
                    {
                        "hotelId": "55555",
                        "accommodations": [
                            {
                                "id": "acc-1",
                                # Real supplier responses echo the stay dates; the request
                                # body is stripped from the expectation, so only these are
                                # available for the field map to find.
                                "checkInDate": "2026-08-01",
                                "checkOutDate": "2026-08-03",
                                "totalPrice": 500.0,
                                "currency": "EUR",
                                "distributions": [{"board": "RO", "roomName": "Twin"}],
                            }
                        ],
                    }
                ]
            }
        },
    }
    for log_type in ("Search", "Packages", "Booking")
}


async def _fetch_tst_detail(log_url: str) -> dict:
    return _TST_DETAILS[log_url]


@pytest.fixture
def ingest_dirs(tmp_path, monkeypatch):
    """Point the ingestor at a temp templates dir so tests never touch the repo's."""
    from app.ingest import template_ingestor

    templates = tmp_path / "templates"
    field_maps = tmp_path / "field-maps"
    monkeypatch.setattr(template_ingestor, "TEMPLATES_DIR", templates)
    monkeypatch.setattr(template_ingestor, "FIELD_MAPS_DIR", field_maps)
    return templates, field_maps


@pytest.mark.asyncio
async def test_ingest_builds_templates_for_a_ui_added_supplier(api_client, ingest_dirs):
    """The whole point: a supplier configured in the UI gets its templates from a SID."""
    from app.ingest.template_ingestor import TemplateIngestor

    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    from app.env_context import set_current_env

    set_current_env("dev")

    templates, field_maps = ingest_dirs
    ingestor = TemplateIngestor(templates_dir=templates, field_maps_dir=field_maps)
    result = await ingestor.ingest_from_list_json(
        "TST", "sid-1", _TST_LIST_JSON, fetch_detail=_fetch_tst_detail
    )

    assert result == 3
    for log_type in ("Search", "Packages", "Booking"):
        assert (templates / "TST" / log_type / "v1.json").exists()

    # The field map is generated from the supplier's own configured key names —
    # TST has no SUPPLIER_MUTABLE_KEYS entry, so this would be empty without that.
    field_map = json.loads((field_maps / "TST.json").read_text())
    assert field_map["paths"]["check_in"], "check_in keys came from mutation_config"
    assert field_map["paths"]["price"]
    assert field_map["paths"]["board"] == [
        "httpResponse.body.body[0].accommodations[0].distributions[0].board"
    ]


@pytest.mark.asyncio
async def test_ingest_ignores_other_suppliers_rows(api_client, ingest_dirs):
    from app.ingest.template_ingestor import TemplateIngestor

    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    from app.env_context import set_current_env

    set_current_env("dev")

    templates, field_maps = ingest_dirs
    ingestor = TemplateIngestor(templates_dir=templates, field_maps_dir=field_maps)
    await ingestor.ingest_from_list_json(
        "TST", "sid-1", _TST_LIST_JSON, fetch_detail=_fetch_tst_detail
    )
    # The HBS row in the same SID must not have produced HBS templates.
    assert not (templates / "HBS").exists()


@pytest.mark.asyncio
async def test_ingest_result_reports_written_missing_and_sources(api_client, ingest_dirs):
    from app.ingest.template_ingestor import TemplateIngestor

    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    from app.env_context import set_current_env

    set_current_env("dev")

    templates, field_maps = ingest_dirs
    ingestor = TemplateIngestor(templates_dir=templates, field_maps_dir=field_maps)
    plugin = __import__("app.plugins", fromlist=["resolve_plugin"]).resolve_plugin("TST")
    result = await ingestor._ingest_supplier(
        plugin, "sid-1", _TST_LIST_JSON["details"], fetch_detail=_fetch_tst_detail
    )

    assert result.written == ["Booking", "Packages", "Search"]
    # TST declares GetOrder and CancelOrder too, and the SID had no rows for them.
    assert result.missing == ["CancelOrder", "GetOrder"]
    assert result.paths["Search"] == "/api/v2/search"
    assert "hotel-connectivity-hbs-adapter" in result.sources_seen
    assert result.field_map_paths > 0


def test_ingest_route_rejects_a_supplier_with_no_source_match(api_client):
    """Without adapter_source_match nothing can match, so say so rather than return empty."""
    payload = {
        **NEW_SUPPLIER,
        "mutation_config": {**NEW_SUPPLIER["mutation_config"], "adapter_source_match": ""},
    }
    api_client.post("/api/suppliers", json=payload, headers=DEV)
    response = api_client.post("/api/suppliers/TST/ingest", json={"sid": "sid-1"}, headers=DEV)
    assert response.status_code == 400
    assert "adapter log source match" in response.json()["detail"]


def test_ingest_route_requires_a_sid(api_client):
    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    assert (
        api_client.post("/api/suppliers/TST/ingest", json={"sid": "  "}, headers=DEV).status_code
        == 422
    )


def test_ingest_route_explains_an_unconfigured_logs_api(api_client, monkeypatch):
    """No LOGS_API_URL is a setup problem, not a 500.

    The URL is forced empty rather than assumed absent: a developer with a real
    backend/.env would otherwise reach the logs API and get a different error.
    """
    import app.config as config_module

    # The route imports get_settings inside its own body, so the patch has to land on
    # app.config itself. Wrap the real accessor rather than fabricate a Settings.
    real_get_settings = config_module.get_settings

    def _no_logs_api(env=None):
        return real_get_settings(env).model_copy(update={"logs_api_url": ""})

    monkeypatch.setattr(config_module, "get_settings", _no_logs_api)

    api_client.post("/api/suppliers", json=NEW_SUPPLIER, headers=DEV)
    response = api_client.post("/api/suppliers/TST/ingest", json={"sid": "sid-1"}, headers=DEV)
    assert response.status_code == 400
    assert "LOGS_API_URL" in response.json()["detail"]
