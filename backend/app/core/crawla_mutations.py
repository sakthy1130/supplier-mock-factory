"""Crawla-specific scenario overrides."""

from __future__ import annotations

from typing import Any
from typing import Optional

from app.models.scenario import SupplierMutation
from app.plugins.json_utils import deep_copy, update_fields_recursive
from app.plugins.room_names import apply_hbs_room_name

PRICE_FIELD_NAMES = {
    "amount",
    "base_amount",
    "maxPrice",
    "maxRate",
    "max_price",
    "minPrice",
    "minRate",
    "min_price",
    "net",
    "netPrice",
    "price",
    "totalAmount",
    "totalPrice",
    "total_amount",
    "value",
}


def apply_supplier_mutation(
    expectation: dict,
    supplier_code: str,
    log_type: str,
    hotel_id: str,
    mutation: Optional[SupplierMutation],
) -> dict:
    if mutation is None:
        return expectation

    result = deep_copy(expectation)
    if mutation.exclude_hotel and supplier_code == "EXP" and log_type in {"Search", "Packages"}:
        return _exclude_exp_hotel(result, hotel_id)

    price = mutation.package_price if log_type == "Packages" else mutation.search_price
    if price is not None:
        if supplier_code == "EXP" and log_type == "Search":
            _apply_exp_search_price_override(result, price)
        else:
            _apply_price_override(result, price)

    if supplier_code == "HBS":
        effective_room_name = (
            mutation.search_room_name if log_type == "Search" and mutation.search_room_name
            else mutation.room_name
        )
        if effective_room_name:
            apply_hbs_room_name(result, effective_room_name)
    if supplier_code == "HBS" and mutation.room_basis:
        _apply_hbs_room_basis(result, mutation.room_basis)
    if supplier_code == "EXP":
        effective_room_name = (
            mutation.search_room_name if log_type == "Search" and mutation.search_room_name
            else mutation.room_name
        )
        if effective_room_name:
            _apply_exp_room_name(result, effective_room_name)
    if supplier_code == "EXP" and mutation.room_basis:
        _apply_exp_room_basis(result, mutation.room_basis)
    if supplier_code == "EXP" and mutation.bed_groups_description:
        _apply_exp_bed_groups_description(result, mutation.bed_groups_description)

    return result


def _exclude_exp_hotel(expectation: dict, hotel_id: str) -> dict:
    body = expectation.get("httpResponse", {}).get("body")
    hotels = body if isinstance(body, list) else body.get("body") if isinstance(body, dict) else None
    if isinstance(hotels, list):
        filtered = [
            item
            for item in hotels
            if str(_extract_property_id(item)) != str(hotel_id)
        ]
        if isinstance(body, list):
            expectation["httpResponse"]["body"] = filtered
        else:
            body["body"] = filtered
        return expectation
    if not isinstance(body, dict):
        return expectation

    hotels_wrapper = body.get("hotels")
    if isinstance(hotels_wrapper, dict):
        hotel_list = hotels_wrapper.get("hotels")
        if isinstance(hotel_list, list):
            hotels_wrapper["hotels"] = [
                item
                for item in hotel_list
                if str(_extract_property_id(item)) != str(hotel_id)
            ]
    return expectation


def _extract_property_id(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    for key in ("property_id", "code", "hotel_id", "atg_id"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _apply_price_override(expectation: dict, price: float) -> None:
    def replace(value: Any) -> Any:
        if isinstance(value, str):
            return f"{price:.2f}"
        if isinstance(value, int):
            return int(round(price))
        if isinstance(value, float):
            return float(price)
        return value

    update_fields_recursive(expectation, {field: replace for field in PRICE_FIELD_NAMES})


def _apply_exp_search_price_override(expectation: dict, price: float) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            occupancy_pricing = node.get("occupancy_pricing")
            if isinstance(occupancy_pricing, dict):
                _scale_exp_occupancy_pricing(occupancy_pricing, price)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(expectation.get("httpResponse", {}).get("body"))


def _scale_exp_occupancy_pricing(occupancy_pricing: dict, desired_total: float) -> None:
    for occ_data in occupancy_pricing.values():
        if not isinstance(occ_data, dict):
            continue
        current_total = _read_exp_inclusive_total(occ_data)
        if current_total is None or current_total <= 0:
            continue
        ratio = desired_total / current_total
        _scale_exp_money_fields(occ_data, ratio)


def _read_exp_inclusive_total(occ_data: dict) -> float | None:
    totals = occ_data.get("totals")
    if not isinstance(totals, dict):
        return None
    inclusive = totals.get("inclusive")
    if not isinstance(inclusive, dict):
        return None
    request_currency = inclusive.get("request_currency")
    if not isinstance(request_currency, dict):
        return None
    return _parse_money(request_currency.get("value"))


def _scale_exp_money_fields(node: Any, ratio: float) -> None:
    if isinstance(node, dict):
        if "value" in node and "currency" in node:
            parsed = _parse_money(node.get("value"))
            if parsed is not None:
                node["value"] = f"{parsed * ratio:.2f}"
        for value in node.values():
            _scale_exp_money_fields(value, ratio)
    elif isinstance(node, list):
        for item in node:
            _scale_exp_money_fields(item, ratio)


def _parse_money(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _apply_hbs_room_basis(expectation: dict, room_basis: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return

    def update_rate(rate: dict) -> None:
        if not isinstance(rate, dict):
            return
        rate["roomBasis"] = room_basis
        if "boardCode" in rate:
            rate["boardCode"] = room_basis
        if "boardName" in rate:
            rate["boardName"] = _board_name(room_basis)

    def update_room(room: dict) -> None:
        if not isinstance(room, dict):
            return
        room["roomBasis"] = room_basis
        rates = room.get("rates")
        if isinstance(rates, list):
            for rate in rates:
                update_rate(rate)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            rooms = node.get("rooms")
            if isinstance(rooms, list):
                for room in rooms:
                    update_room(room)
                    walk(room)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)


def _apply_exp_bed_groups_description(expectation: dict, description: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    if isinstance(body, dict):
        entries = body.get("body")
    elif isinstance(body, list):
        entries = body
    else:
        return
    if not isinstance(entries, list):
        return
    for prop in entries:
        if not isinstance(prop, dict):
            continue
        for room in prop.get("rooms") or []:
            if not isinstance(room, dict):
                continue
            for rate in room.get("rates") or []:
                if not isinstance(rate, dict):
                    continue
                bed_groups = rate.get("bed_groups")
                if isinstance(bed_groups, dict):
                    for bg in bed_groups.values():
                        if isinstance(bg, dict):
                            bg["description"] = description


# Amenity IDs that represent a meal plan in the EXP/Rapid API.
# Non-meal amenities (WiFi, parking, etc.) are intentionally excluded.
_EXP_MEAL_AMENITY_IDS: frozenset[str] = frozenset({
    "2098", "2102", "2103", "2104", "2105", "2106", "2107", "2111",
    "2193", "2194", "2205", "2206", "2207", "2209", "2210", "2211",
    "1073742621", "1073742625", "1073742626", "1073742786", "1073742857", "1073742551",
})

# Canonical amenity (id, name) to inject per board code.
_EXP_BOARD_AMENITY: dict[str, tuple[str, str]] = {
    "BB": ("2098", "Free Breakfast"),
    "HB": ("2206", "Half Board"),
    "FB": ("2207", "Full Board"),
    "AI": ("2111", "All-Inclusive"),
}


def _apply_exp_room_basis(expectation: dict, room_basis: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    if isinstance(body, dict):
        entries = body.get("body")
    elif isinstance(body, list):
        entries = body
    else:
        return
    if not isinstance(entries, list):
        return
    amenity_entry = _EXP_BOARD_AMENITY.get(room_basis.upper() if room_basis else "")
    for prop in entries:
        if not isinstance(prop, dict):
            continue
        for room in prop.get("rooms") or []:
            if not isinstance(room, dict):
                continue
            for rate in room.get("rates") or []:
                if not isinstance(rate, dict):
                    continue
                rate.pop("meal_plan", None)
                amenities = rate.setdefault("amenities", {})
                if not isinstance(amenities, dict):
                    continue
                for key in list(amenities):
                    if str(key) in _EXP_MEAL_AMENITY_IDS:
                        del amenities[key]
                if amenity_entry:
                    amenity_id, amenity_name = amenity_entry
                    amenities[amenity_id] = {"id": amenity_id, "name": amenity_name}


def _apply_exp_room_name(expectation: dict, room_name: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    # EXP body is either a list of property entries or {"body": [...]}
    if isinstance(body, dict):
        entries = body.get("body")
    elif isinstance(body, list):
        entries = body
    else:
        return
    if not isinstance(entries, list):
        return
    for prop in entries:
        if not isinstance(prop, dict):
            continue
        for room in prop.get("rooms") or []:
            if isinstance(room, dict) and "room_name" in room:
                room["room_name"] = room_name


def _board_name(room_basis: str) -> str:
    mapping = {
        "RO": "ROOM ONLY",
        "BB": "BED AND BREAKFAST",
        "HB": "HALF BOARD",
        "FB": "FULL BOARD",
        "AI": "ALL INCLUSIVE",
    }
    return mapping.get(room_basis.upper(), room_basis)
