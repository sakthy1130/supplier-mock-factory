"""Seed the suppliers table from the constants that used to define suppliers in code.

This IS the migration for HBS/EXP/RHK/CHC/EXT: every value below is lifted verbatim
from the module it used to live in, so a seeded row reproduces today's behaviour
exactly. Once seeded, the Suppliers screen owns this data and the constants here are
only ever read again on a fresh database.

Idempotent per (code, env) — an existing row is never overwritten, so edits made in
the UI survive a restart.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.core.chc_paths import CHC_CONTRACT_OPT_DEFAULTS
from app.core.exp_paths import EXP_CONTRACT_OPT_DEFAULTS, EXP_MOCK_PATH_SUFFIX
from app.core.ext_paths import (
    EXT_CANONICAL_BASE,
    EXT_CONTRACT_OPT_DEFAULTS,
    EXT_LOG_TYPE_TO_OPT_FIELD,
    EXT_MOCK_PATH_SUFFIX,
)
from app.core.hbs_paths import (
    HBS_CANONICAL_BASE,
    HBS_CONTRACT_OPT_DEFAULTS,
    HBS_LOG_TYPE_TO_OPT_FIELD,
    HBS_MOCK_PATH_SUFFIX,
)
from app.core.opt_fields import EXP_LOG_TYPE_TO_OVERRIDE_FIELD, LOG_TYPE_TO_OPT_FIELD
from app.db.models import SupplierRecord

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIELD_MAPS_DIR = REPO_ROOT / "field-maps"

SEED_ENVS = ("dev", "stg")

# Backoffice ids per env. Dev does NOT share stg's supplier records — a dev contract
# referencing stg's HBS _id caused a NullPointerException in hotel-connectivity-core
# (confirmed 2026-07-20). RHK/CHC/EXT dev ids were never investigated and still carry
# stg's values; fix them in the Suppliers screen if they NPE too.
_BACKOFFICE_IDS: dict[str, dict[str, tuple[str, int]]] = {
    "stg": {
        "HBS": ("5fd5fefb1a4e866f7b3cea44", 100004),
        "EXP": ("5fb648d84b949648780c1b74", 100002),
        "RHK": ("652cd63a90fb03102f226030", 100671),
        "CHC": ("69ef11d11a41325a74bab5da", 107017),
        "EXT": ("642c33cbff075a612ab6ad06", 100423),
    },
    "dev": {
        "HBS": ("60059008536a5c532c0936a2", 100006),
        "EXP": ("5fb275f9c67d8a6ccb1e90e3", 100002),
        "RHK": ("652cd63a90fb03102f226030", 100671),
        "CHC": ("69ef11d11a41325a74bab5da", 107017),
        "EXT": ("642c33cbff075a612ab6ad06", 100423),
    },
}

_FULL_BOOKING_FLOW = ["Search", "Packages", "PreBooking", "Booking", "GetOrder", "CancelOrder"]


def _reference_contract_id(code: str, env: str) -> str:
    """The env's *_REFERENCE_CONTRACT_ID, read once at seed time."""
    settings = get_settings(env)
    return getattr(settings, f"{code.lower()}_reference_contract_id", "") or ""


def _field_map(code: str) -> dict[str, Any] | None:
    path = FIELD_MAPS_DIR / f"{code}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Seed: could not read field-maps/%s.json", code)
        return None


# ── Per-supplier definitions ────────────────────────────────────────────────────
# mock_config mirrors the *_paths.py modules and the if-chains in
# contract_provisioner / mock_urls / expectation_utils.
# mutation_config mirrors SUPPLIER_MUTABLE_KEYS plus the booking-id branches in
# booking_id_injector. packages_path is only set where the payload really has one
# array of rates — HBS and EXP spread theirs across nested rooms, and their
# hand-written plugins handle that, so the generic path stays empty for them.

# Per-scenario mock paths for Choice's Derby deployment. Two reasons this is not empty:
# MockServer matches on path + method only, so Packages and PreBooking both sitting on
# /api/go/bookingusb/v4/availability meant one shadowed the other; and every Derby
# scenario would otherwise register identical paths, letting concurrent scenarios (or a
# sibling Derby supplier) answer each other's calls. The /{namespace}/ prefix isolates
# them, and the contract opt URLs are built from these same paths so they stay in step.
CHC_MOCK_PATH_SUFFIX: dict[str, str] = {
    "Search": "api/go/shoppingengine/v4/shopping/multihotels",
    "Packages": "api/go/bookingusb/v4/availability",
    "CancellationPolicy": "api/go/bookingusb/v4/cancellationpolicy",
    "PreBooking": "api/go/bookingusb/v4/livecheck",
    "Booking": "api/go/bookingusb/v4/reservation/book",
    "GetOrder": "api/go/bookingusb/v4/reservation/detail",
    "CancelOrder": "api/go/bookingusb/v4/reservation/cancel",
}


SEED_SUPPLIERS: list[dict[str, Any]] = [
    {
        "code": "HBS",
        "name": "HotelBeds",
        "supplier_type": "net",
        "default_supplier_currency": "EUR",
        "default_contract_currency": "USD",
        "log_types": _FULL_BOOKING_FLOW,
        "package_log_types": ["Search", "Packages"],
        "ui_color": "#5b63c9",
        "mock_config": {
            "canonical_base": HBS_CANONICAL_BASE,
            "mock_path_suffix": HBS_MOCK_PATH_SUFFIX,
            "opt_field_map": HBS_LOG_TYPE_TO_OPT_FIELD,
            "opt_source": "canonical",
            "path_rewrite": True,
            "opt_defaults": HBS_CONTRACT_OPT_DEFAULTS,
            "opt_defaults_fill": "blank",
            "always_enforce_opt": [
                "availabilityTimeoutSeconds",
                "cancellationPoliciesTimeoutSeconds",
            ],
            "set_mock_server_url": True,
            "dynamic_market_type": "DynamicMarkupTarget",
            # GetOrder is addressed as .../GetOrderBooking/<bookingId>.
            "booking_id_in_get_order_path": True,
        },
        "mutation_config": {
            "check_in_keys": ["checkIn"],
            "check_out_keys": ["checkOut"],
            "price_keys": ["amount", "net", "gross", "sellingRate"],
            "board_key": "boardCode",
            "room_name_key": "name",
            "package_id_key": "rateKey",
            "hotel_id_key": "hotelId",
            "adapter_source_match": "hotelbeds",
            "booking_id_keys": ["reference", "distributorResId", "derbyResId"],
            "booking_id_fallback_paths": ["httpResponse.body.booking.reference"],
            "booking_id_format": "prefix_digits",
        },
    },
    {
        "code": "EXP",
        "name": "Expedia",
        "supplier_type": "gross",
        "default_supplier_currency": "USD",
        "default_contract_currency": "USD",
        "log_types": _FULL_BOOKING_FLOW,
        "package_log_types": ["Search", "Packages"],
        "ui_color": "#b23e73",
        "mock_config": {
            # PreBooking/Booking/GetOrder/CancelOrder keep their canonical /v3/... paths;
            # only Search and Packages get namespaced onto /{namespace}/<suffix>.
            "mock_path_suffix": EXP_MOCK_PATH_SUFFIX,
            "opt_field_map": EXP_LOG_TYPE_TO_OVERRIDE_FIELD,
            "opt_source": "ingested",
            "path_namespaced": True,
            "unwrap_adapter_log_body": True,
            "opt_defaults": EXP_CONTRACT_OPT_DEFAULTS,
            "opt_defaults_fill": "missing",
            # Reference contracts sometimes carry enableGenericBedding: true, which makes
            # the adapter emit an extra not-for-sale package per rate.
            "forced_opt": {"enableGenericBedding": False},
            "set_mock_server_url": False,
            "dynamic_market_type": "MarketPriceSource",
        },
        "mutation_config": {
            "check_in_keys": ["checkInDate"],
            "check_out_keys": ["checkOutDate"],
            "price_keys": ["netPrice", "totalPrice"],
            "board_key": "meal_plan",
            "room_name_key": "name",
            "package_id_key": "rateKey",
            "hotel_id_key": "propertyId",
            "refundable_key": "refundable",
            "adapter_source_match": "expedia",
            "booking_id_keys": ["itinerary_id", "distributorResId", "derbyResId"],
            "booking_id_fallback_paths": ["httpResponse.body.itinerary_id"],
            "booking_id_format": "digits",
        },
    },
    {
        "code": "RHK",
        "name": "RateHawk",
        "supplier_type": "net",
        "default_supplier_currency": "USD",
        "default_contract_currency": "USD",
        "log_types": _FULL_BOOKING_FLOW,
        "package_log_types": ["Search", "Packages"],
        "ui_color": "#c1652f",
        "mock_config": {
            # No canonical paths — RHK serves whatever the ingested templates carry.
            "opt_field_map": LOG_TYPE_TO_OPT_FIELD,
            "opt_source": "ingested",
            # Not touched by the old _apply_hbs_contract_defaults, so the cloned
            # reference contract's own value is left alone.
            "dynamic_market_type": None,
        },
        "mutation_config": {
            "check_in_keys": ["checkin_at", "check_in", "checkin"],
            "check_out_keys": ["checkout_at", "check_out", "checkout"],
            "price_keys": ["amount", "show_amount"],
            "board_key": "meal",
            "room_name_key": "room_name",
            "package_id_key": "match_hash",
            "hotel_id_key": "hid",
            "refundable_key": "refundable",
            "packages_path": "httpResponse.body.data.hotels.0.rates",
            "adapter_source_match": "ratehawk",
            "booking_id_keys": ["partner_order_id", "order_id"],
            "booking_id_paths_by_log_type": {
                "Booking": ["httpResponse.body.debug.request.partner.partner_order_id"],
                "GetOrder": [
                    "httpResponse.body.data.orders[0].order_id",
                    "httpResponse.body.data.orders[0].supplier_data.order_id",
                    "httpResponse.body.data.orders[0].partner_data.order_id",
                ],
                "CancelOrder": ["httpResponse.body.debug.request.partner_order_id"],
            },
            "booking_id_fallback_paths": [
                "httpResponse.body.debug.request.partner.partner_order_id"
            ],
            "booking_id_format": "prefix_hex",
        },
    },
    {
        "code": "CHC",
        "name": "Choice",
        "supplier_type": "net",
        "default_supplier_currency": "SAR",
        "default_contract_currency": "USD",
        "log_types": _FULL_BOOKING_FLOW,
        "package_log_types": ["Search", "Packages", "PreBooking", "GetOrder"],
        "ui_color": "#7d4f85",
        "mock_config": {
            "opt_field_map": LOG_TYPE_TO_OPT_FIELD,
            "opt_source": "ingested",
            "opt_defaults": {
                k: v
                for k, v in CHC_CONTRACT_OPT_DEFAULTS.items()
                if k != "isCancellationPolicyOneSlot"
            },
            "opt_defaults_fill": "blank",
            # Derby BTS collapses multi-part cancel codes to one fee tier when set.
            "forced_opt": {"isCancellationPolicyOneSlot": True},
            "set_mock_server_url": True,
            "dynamic_market_type": "DynamicMarkupTarget",
            "path_namespaced": True,
            "mock_path_suffix": CHC_MOCK_PATH_SUFFIX,
        },
        "mutation_config": {
            "check_in_keys": ["checkin"],
            "check_out_keys": ["checkout"],
            "price_keys": ["amountBeforeTax", "amountAfterTax"],
            "board_key": "mealPlan",
            "room_name_key": "roomId",
            "package_id_key": "rateId",
            "hotel_id_key": "hotelId",
            "currency_key": "currency",
            "packages_path": "httpResponse.body.roomRates",
            "adapter_source_match": "derby",
            "booking_id_keys": ["distributorResId", "derbyResId", "supplierResId"],
            "booking_id_fallback_paths": [
                "httpResponse.body.distributorResId",
                "httpResponse.body.derbyResId",
            ],
            "booking_id_format": "digits",
        },
    },
    {
        "code": "EXT",
        "name": "Extranet",
        "supplier_type": "net",
        "default_supplier_currency": "EUR",
        "default_contract_currency": "USD",
        # No PreBooking — the Extranet flow books straight off the distribution.
        "log_types": ["Search", "Packages", "Booking", "GetOrder", "CancelOrder"],
        "package_log_types": ["Search", "Packages"],
        "ui_color": "#1b8080",
        "mock_config": {
            "canonical_base": EXT_CANONICAL_BASE,
            "mock_path_suffix": EXT_MOCK_PATH_SUFFIX,
            "opt_field_map": EXT_LOG_TYPE_TO_OPT_FIELD,
            "opt_source": "ingested",
            "opt_defaults": EXT_CONTRACT_OPT_DEFAULTS,
            "opt_defaults_fill": "blank",
            "always_enforce_opt": [
                "availabilityTimeoutSeconds",
                "cancellationPoliciesTimeoutSeconds",
            ],
            "set_mock_server_url": True,
            "dynamic_market_type": "DynamicMarkupTarget",
        },
        # EXT never had a SUPPLIER_MUTABLE_KEYS entry, so field-map generation
        # produced nothing for it — these keys are read off plugins/ext.py.
        "mutation_config": {
            "check_in_keys": ["checkInDate", "checkin"],
            "check_out_keys": ["checkOutDate", "checkout"],
            "price_keys": ["totalPrice", "netPrice", "initialPrice"],
            "board_key": "board",
            "room_name_key": "roomName",
            "currency_key": "currency",
            "package_id_key": "id",
            "hotel_id_key": "hotelId",
            "board_values": ["RO", "BB", "HB", "FB", "AI", "IF", "SR", "IR"],
            "packages_path": "httpResponse.body.body.0.accommodations",
            "adapter_source_match": "extranet",
            "booking_id_keys": ["bookingId", "reservationId"],
            "booking_id_fallback_paths": [
                "httpResponse.body.bookingId",
                "httpResponse.body.reservations[0].bookingId",
            ],
            "booking_id_format": "digits",
        },
    },
]


def seed_suppliers(session_factory) -> int:
    """Insert any missing (code, env) supplier rows. Returns how many were added."""
    added = 0
    with session_factory() as session:
        existing = {
            (code, env)
            for code, env in session.execute(
                select(SupplierRecord.code, SupplierRecord.env)
            ).all()
        }
        for env in SEED_ENVS:
            for spec in SEED_SUPPLIERS:
                code = spec["code"]
                if (code, env) in existing:
                    continue
                supplier_id, auto_id = _BACKOFFICE_IDS[env][code]
                session.add(
                    SupplierRecord(
                        id=str(uuid.uuid4()),
                        code=code,
                        env=env,
                        name=spec["name"],
                        supplier_type=spec["supplier_type"],
                        supplier_id=supplier_id,
                        auto_id=auto_id,
                        reference_contract_id=_reference_contract_id(code, env),
                        default_supplier_currency=spec["default_supplier_currency"],
                        default_contract_currency=spec["default_contract_currency"],
                        log_types_json=list(spec["log_types"]),
                        package_log_types_json=list(spec["package_log_types"]),
                        ui_color=spec["ui_color"],
                        mock_config_json=dict(spec["mock_config"]),
                        mutation_config_json=dict(spec["mutation_config"]),
                        field_map_json=_field_map(code),
                    )
                )
                added += 1
        if added:
            session.commit()
            log.info("Seed: added %d supplier rows", added)
    return added
