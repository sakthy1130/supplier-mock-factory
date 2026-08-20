"""Build field-maps/{supplier}.json from ingested templates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.supplier import MutationConfig

# Seeded into each supplier's mutation_config on first boot (see db/seed_suppliers.py)
# and read from there at runtime. Kept here as the seed source, and as the fallback for
# ingest runs that predate the suppliers table.
SUPPLIER_MUTABLE_KEYS: dict[str, dict[str, list[str]]] = {
    "HBS": {
        "check_in": ["checkIn"],
        "check_out": ["checkOut"],
        "booking_id": ["reference"],
        "distributor_res_id": ["distributorResId"],
        "derby_res_id": ["derbyResId"],
        "hotel_id": ["hotelId", "hotelCode", "code"],
        "price": ["amount", "net", "gross", "sellingRate"],
        "package_id": ["packageId", "rateKey", "roomCode"],
    },
    "EXP": {
        "check_in": ["checkInDate"],
        "check_out": ["checkOutDate"],
        "booking_id": ["itinerary_id"],
        "distributor_res_id": ["distributorResId"],
        "derby_res_id": ["derbyResId"],
        "hotel_id": ["hotelId", "propertyId"],
        "price": ["netPrice", "totalPrice"],
        "package_id": ["packageId", "rateKey"],
        "price_per_night": ["netPricePerNight", "totalPricePerNight"],
    },
    "RHK": {
        "check_in": ["checkin_at", "check_in", "checkin"],
        "check_out": ["checkout_at", "check_out", "checkout"],
        "booking_id": ["partner_order_id", "order_id"],
        "hotel_id": ["hid", "hotelId"],
        "price": ["amount", "show_amount", "daily_prices"],
        "package_id": ["match_hash", "book_hash", "search_hash"],
    },
    # Derby/OTA-style payload via hotels-derby-bts-adapter.
    "CHC": {
        "check_in": ["checkin"],
        "check_out": ["checkout"],
        "booking_id": ["distributorResId", "derbyResId", "supplierResId"],
        "hotel_id": ["hotelId"],
        "price": ["amountBeforeTax", "amountAfterTax"],
        "package_id": ["roomId", "rateId"],
    },
}


def _keys_from_mutation_config(config: "MutationConfig") -> dict[str, list[str]]:
    """Map a supplier's mutation config onto the field-map's key categories."""
    single = {
        "hotel_id": config.hotel_id_key,
        "package_id": config.package_id_key,
        "board": config.board_key,
        "room_name": config.room_name_key,
        "currency": config.currency_key,
    }
    categories: dict[str, list[str]] = {
        "check_in": list(config.check_in_keys),
        "check_out": list(config.check_out_keys),
        "price": list(config.price_keys),
        "booking_id": list(config.booking_id_keys),
    }
    for category, key in single.items():
        if key:
            categories[category] = [key]
    return {category: keys for category, keys in categories.items() if keys}


class FieldMapGenerator:
    def generate(
        self,
        supplier_code: str,
        templates: dict[str, dict],
        mutation_config: "MutationConfig | None" = None,
    ) -> dict:
        key_config = (
            _keys_from_mutation_config(mutation_config)
            if mutation_config is not None
            else SUPPLIER_MUTABLE_KEYS.get(supplier_code, {})
        )
        paths: dict[str, list[str]] = {}

        for category, key_names in key_config.items():
            found: set[str] = set()
            for template in templates.values():
                for key_name in key_names:
                    for path in _find_paths(template, key_name):
                        found.add(path)
            paths[category] = sorted(found)

        return {
            "supplier": supplier_code,
            "log_types": sorted(templates.keys()),
            "paths": paths,
        }


def _find_paths(node: Any, target_key: str, prefix: str = "") -> list[str]:
    results: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if key == target_key:
                results.append(path)
            results.extend(_find_paths(value, target_key, path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            path = f"{prefix}[{index}]"
            results.extend(_find_paths(item, target_key, path))
    return results
