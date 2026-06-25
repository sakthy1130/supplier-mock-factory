"""Apply scenario supplier_currency to supplier mock payloads."""

from __future__ import annotations

from typing import Any


def apply_hbs_supplier_currency(expectation: dict, currency: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return

    hotels_wrapper = body.get("hotels")
    if isinstance(hotels_wrapper, dict):
        _set_iso_currency_field(hotels_wrapper, currency)
        hotel_list = hotels_wrapper.get("hotels")
        if isinstance(hotel_list, list):
            for hotel in hotel_list:
                if isinstance(hotel, dict):
                    _set_iso_currency_field(hotel, currency)
                    _apply_hbs_rate_tax_currency(hotel, currency)

    hotel = body.get("hotel")
    if isinstance(hotel, dict):
        _set_iso_currency_field(hotel, currency)
        _apply_hbs_rate_tax_currency(hotel, currency)

    booking = body.get("booking")
    if isinstance(booking, dict):
        _set_iso_currency_field(booking, currency)
        hotel = booking.get("hotel")
        if isinstance(hotel, dict):
            _set_iso_currency_field(hotel, currency)
            _apply_hbs_rate_tax_currency(hotel, currency)


def apply_exp_supplier_currency(expectation: dict, currency: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    _walk_exp_currency(body, currency)


def apply_rhk_supplier_currency(expectation: dict, currency: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return
    data = body.get("data")
    if isinstance(data, dict):
        _set_iso_currency_field(data, currency)
        hotels = data.get("hotels")
        if isinstance(hotels, list):
            for hotel in hotels:
                if isinstance(hotel, dict):
                    _apply_rhk_rate_currency(hotel, currency)
        orders = data.get("orders")
        if isinstance(orders, list):
            for order in orders:
                if isinstance(order, dict):
                    _walk_rhk_currency_codes(order, currency)


def apply_chc_supplier_currency(expectation: dict, currency: str) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    if not isinstance(body, dict):
        return

    hotels = body.get("availHotels")
    if isinstance(hotels, list):
        for hotel in hotels:
            if isinstance(hotel, dict):
                _set_rate_currency(hotel.get("availRoomRates"), currency)

    _set_rate_currency(body.get("roomRates"), currency)

    reservations = body.get("reservations")
    if isinstance(reservations, list):
        for reservation in reservations:
            if not isinstance(reservation, dict):
                continue
            _set_rate_currency(reservation.get("roomRates"), currency)


def _set_rate_currency(rates: object, currency: str) -> None:
    if not isinstance(rates, list):
        return
    for rate in rates:
        if isinstance(rate, dict):
            rate["currency"] = currency


def _apply_hbs_rate_tax_currency(node: dict, currency: str) -> None:
    rooms = node.get("rooms")
    if not isinstance(rooms, list):
        return
    for room in rooms:
        if not isinstance(room, dict):
            continue
        rates = room.get("rates")
        if not isinstance(rates, list):
            continue
        for rate in rates:
            if not isinstance(rate, dict):
                continue
            taxes = rate.get("taxes")
            if isinstance(taxes, dict):
                tax_items = taxes.get("taxes")
                if isinstance(tax_items, list):
                    for tax in tax_items:
                        if isinstance(tax, dict):
                            _set_iso_currency_field(tax, currency)


def _apply_rhk_rate_currency(hotel: dict, currency: str) -> None:
    rates = hotel.get("rates")
    if not isinstance(rates, list):
        return
    for rate in rates:
        if isinstance(rate, dict):
            _walk_rhk_currency_codes(rate, currency)


def _walk_rhk_currency_codes(node: Any, currency: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "currency_code" and isinstance(value, str):
                node[key] = currency
            else:
                _walk_rhk_currency_codes(value, currency)
    elif isinstance(node, list):
        for item in node:
            _walk_rhk_currency_codes(item, currency)


def _walk_exp_currency(node: Any, currency: str) -> None:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key == "currency" and isinstance(value, str) and len(value) == 3:
                node[key] = currency
            else:
                _walk_exp_currency(value, currency)
    elif isinstance(node, list):
        for item in node:
            _walk_exp_currency(item, currency)


def _set_iso_currency_field(node: dict, currency: str) -> None:
    if "currency" in node and isinstance(node["currency"], str):
        node["currency"] = currency
