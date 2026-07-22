"""Supplier metadata for contract provisioning, keyed by environment.

Dev does NOT share stg's Backoffice supplier records — confirmed 2026-07-20 after a
dev scenario's HBS contract caused a NullPointerException in hotel-connectivity-core
(ContractConfigServiceImpl) because it referenced stg's HBS supplier _id, which
returns 500 "Cannot find Supplier of id" against the dev Backoffice
(GET /api/supplier/{id}). Real dev ids for HBS/EXP were pulled from
GET /api/supplier/summary (paginated; /api/supplier/all omits _id) and verified with
GET /api/supplier/{_id} -> 200 in dev. RHK/CHC dev ids were NOT investigated (out of
scope for now) and still point at stg's values — do not assume they work in dev.
"""

from __future__ import annotations

from app.env_context import get_current_env

_SupplierRegistry = dict[str, dict[str, "str | int | dict[str, str | int]"]]

_STG_REGISTRY: _SupplierRegistry = {
    "HBS": {
        "supplier_id": "5fd5fefb1a4e866f7b3cea44",
        "auto_id": 100004,
        "code": "HBS",
        "name": "HotelBeds",
        "supplier_type": "net",
        "supplier_detail": {
            "code": "HBS",
            "name": "HotelBeds",
            "autoId": 100004,
        },
    },
    "EXP": {
        "supplier_id": "5fb648d84b949648780c1b74",
        "auto_id": 100002,
        "code": "EXP",
        "name": "Expedia",
        "supplier_type": "gross",
        "supplier_detail": {
            "code": "EXP",
            "name": "Expedia",
            "autoId": 100002,
        },
    },
    "RHK": {
        "supplier_id": "652cd63a90fb03102f226030",
        "auto_id": 100671,
        "code": "RHK",
        "name": "RateHawk",
        "supplier_type": "net",
        "supplier_detail": {
            "code": "RHK",
            "name": "RateHawk",
            "autoId": 100671,
        },
    },
    # TODO(CHC): replace placeholders with real staging supplier_id / auto_id / supplier_type.
    "CHC": {
        "supplier_id": "69ef11d11a41325a74bab5da",
        "auto_id": 107017,
        "code": "CHC",
        "name": "Choice",
        "supplier_type": "net",
        "supplier_detail": {
            "code": "CHC",
            "name": "Choice",
            "autoId": 107017,
        },
    },
}

# Dev's own confirmed supplier ids for HBS/EXP (see module docstring). RHK/CHC are
# copied from stg as an unverified placeholder — fix the same way if they NPE too.
_DEV_REGISTRY: _SupplierRegistry = {
    **_STG_REGISTRY,
    "HBS": {
        "supplier_id": "60059008536a5c532c0936a2",
        "auto_id": 100006,
        "code": "HBS",
        "name": "HotelBeds",
        "supplier_type": "net",
        "supplier_detail": {
            "code": "HBS",
            "name": "HotelBeds",
            "autoId": 100006,
        },
    },
    "EXP": {
        "supplier_id": "5fb275f9c67d8a6ccb1e90e3",
        "auto_id": 100002,
        "code": "EXP",
        "name": "Expedia",
        "supplier_type": "gross",
        "supplier_detail": {
            "code": "EXP",
            "name": "Expedia",
            "autoId": 100002,
        },
    },
}

_REGISTRY_BY_ENV: dict[str, _SupplierRegistry] = {
    "dev": _DEV_REGISTRY,
    "stg": _STG_REGISTRY,
}


def get_supplier_registry(env: str | None = None) -> _SupplierRegistry:
    """Supplier metadata for the given env; defaults to the active env (contextvar)."""
    resolved = env or get_current_env()
    return _REGISTRY_BY_ENV.get(resolved, _STG_REGISTRY)
