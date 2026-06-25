"""Staging supplier metadata for contract provisioning."""

from __future__ import annotations

SUPPLIER_REGISTRY: dict[str, dict[str, str | int | dict[str, str | int]]] = {
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
