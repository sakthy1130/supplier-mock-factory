"""Shared room display-name helpers for supplier mock plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.scenario import PackageSpec

DEFAULT_ROOM_NAME = "1 Double Bed, Nonsmoking"


def normalized_room_names(spec: PackageSpec) -> list[str]:
    names = [name.strip() for name in spec.room_names if name and name.strip()]
    if not names:
        names = [DEFAULT_ROOM_NAME]
    while len(names) < spec.count:
        names.append(names[-1])
    return names[: spec.count]


def _set_room_name(room: dict, room_name: str) -> None:
    if "name" in room or "rates" in room:
        room["name"] = room_name
        room["originalRoomName"] = room_name
        existing = room.get("roomName")
        if isinstance(existing, dict):
            existing["en"] = room_name
        else:
            room["roomName"] = {"en": room_name}


def apply_hbs_room_name(expectation: dict, room_name: str) -> None:
    """Set the same display name on every HBS ``rooms[]`` entry in an expectation."""
    apply_hbs_room_names(expectation, [room_name])


def apply_hbs_room_names(expectation: dict, room_names: list[str]) -> None:
    """Set display names on HBS ``rooms[]`` entries (one name per room, by index)."""
    if not room_names:
        return
    body = expectation.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return

    rooms = _primary_rooms(body)
    if rooms is None:
        return

    uniform = len(set(room_names)) == 1
    for index, room in enumerate(rooms):
        if not isinstance(room, dict):
            continue
        name = room_names[0] if uniform else room_names[index if index < len(room_names) else -1]
        _set_room_name(room, name)


def apply_exp_room_name(expectation: dict, room_name: str) -> None:
    apply_exp_room_names(expectation, [room_name])


def apply_exp_room_names(expectation: dict, room_names: list[str]) -> None:
    """Set room_name on EXP property rooms (one name per room, by index)."""
    if not room_names:
        return
    entries = _exp_property_entries(expectation)
    if not entries:
        return

    uniform = len(set(room_names)) == 1
    for prop in entries:
        rooms = prop.get("rooms")
        if not isinstance(rooms, list):
            continue
        for index, room in enumerate(rooms):
            if not isinstance(room, dict) or "room_name" not in room:
                continue
            name = room_names[0] if uniform else room_names[index if index < len(room_names) else -1]
            room["room_name"] = name


def apply_rhk_room_names(expectation: dict, room_names: list[str]) -> None:
    """Set room_name on each RHK rate (one name per package index)."""
    if not room_names:
        return
    body = expectation.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return
    data = body.get("data")
    if not isinstance(data, dict):
        return
    hotels = data.get("hotels")
    if not isinstance(hotels, list) or not hotels or not isinstance(hotels[0], dict):
        return
    rates = hotels[0].get("rates")
    if not isinstance(rates, list):
        return
    for index, rate in enumerate(rates):
        if isinstance(rate, dict) and "room_name" in rate:
            rate["room_name"] = room_names[index if index < len(room_names) else -1]


def _exp_property_entries(expectation: dict) -> list[dict]:
    body = expectation.get("httpResponse", {}).get("body")
    if isinstance(body, dict):
        properties = body.get("body")
        if isinstance(properties, list):
            return [entry for entry in properties if isinstance(entry, dict)]
    if isinstance(body, list):
        return [entry for entry in body if isinstance(entry, dict)]
    return []


def _primary_rooms(body: dict) -> list | None:
    hotel = body.get("hotel")
    if isinstance(hotel, dict):
        rooms = hotel.get("rooms")
        if isinstance(rooms, list):
            return rooms

    hotels_wrapper = body.get("hotels")
    if isinstance(hotels_wrapper, dict):
        hotel_list = hotels_wrapper.get("hotels")
        if isinstance(hotel_list, list) and hotel_list and isinstance(hotel_list[0], dict):
            rooms = hotel_list[0].get("rooms")
            if isinstance(rooms, list):
                return rooms
    return None
