"""EXP supplier plugin. Port SupplierRankingExtJsonUtils."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.core.exp_paths import build_exp_price_check_href, extract_price_check_token
from app.models.scenario import PackageSpec
from app.plugins.base import SupplierMockPlugin
from app.plugins.room_names import apply_exp_room_names, normalized_room_names
from app.plugins.supplier_currency import apply_exp_supplier_currency
from app.plugins.json_utils import (
    deep_copy,
    replace_url_query_param,
    update_fields_recursive,
    walk_nodes,
)

LOG_TYPES = [
    "Search",
    "Packages",
    "CancellationPolicy",
    "PreBooking",
    "Booking",
    "GetOrder",
    "CancelOrder",
]

_PROPERTY_HREF_RE = re.compile(r"/v3/properties/\d+")


class ExpMockPlugin(SupplierMockPlugin):
    code = "EXP"

    def matches_adapter_source(self, source: str) -> bool:
        """Match e.g. hotels-exp-adapter-service-staging."""
        s = source.lower()
        return "hotel" in s and "exp" in s and "adapter" in s

    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        result = deep_copy(expectation)
        update_fields_recursive(
            result,
            {
                "checkInDate": lambda _value: check_in,
                "checkOutDate": lambda _value: check_out,
            },
        )

        for node in walk_nodes(result):
            if isinstance(node, dict) and isinstance(node.get("url"), str):
                url = node["url"]
                node["url"] = replace_url_query_param(
                    replace_url_query_param(url, "checkin", check_in),
                    "checkout",
                    check_out,
                )
        return result

    def mutate_packages(
        self,
        expectation: dict,
        spec: PackageSpec,
        hotel_id: str,
        check_in: str,
        check_out: str,
        log_type: str,
    ) -> dict:
        result = deep_copy(expectation)
        refundable = _normalized_refundable(spec)
        prices = _normalized_prices(spec)

        for node in walk_nodes(result):
            if isinstance(node, dict) and isinstance(node.get("url"), str):
                url = node["url"]
                if "property_id=" in url:
                    node["url"] = _replace_primary_property_id(url, hotel_id)

        for property_entry in _exp_property_entries(result):
            property_entry["property_id"] = str(hotel_id)
            rooms = property_entry.get("rooms")
            if not isinstance(rooms, list) or not rooms:
                continue
            room = rooms[0]
            if not isinstance(room, dict):
                continue
            room_id = str(room.get("id", ""))
            rates = room.get("rates")
            if not isinstance(rates, list) or not rates:
                continue

            template_rate = deep_copy(rates[0])
            new_rates = []
            for index in range(spec.count):
                rate = deep_copy(template_rate)
                price = prices[index]
                rate["refundable"] = refundable[index]
                _ensure_distribution(rate)
                _apply_exp_prices(rate, check_in, check_out, price)
                _rename_occupancy_key(rate, "2")
                _strip_non_standard_exp_occ_fields(rate)
                _trim_bed_groups(rate)
                rate_id = str(rate.get("id", ""))
                _rewrite_property_hrefs(rate, hotel_id, room_id, rate_id)
                new_rates.append(rate)

            room_names = normalized_room_names(spec)
            if len(set(room_names)) == 1 or log_type == "Search":
                if log_type == "Search":
                    room["rates"] = [new_rates[0]] if new_rates else []
                else:
                    room["rates"] = new_rates
                if "room_name" in room:
                    room["room_name"] = room_names[0]
                property_entry["rooms"] = [room]
            else:
                new_rooms = []
                for index, rate in enumerate(new_rates):
                    room_copy = deep_copy(room)
                    room_copy["rates"] = [rate]
                    if "room_name" in room_copy:
                        room_copy["room_name"] = room_names[index]
                    new_rooms.append(room_copy)
                property_entry["rooms"] = new_rooms

            if new_rates:
                primary = new_rates[0]
                rate_id = str(primary.get("id", ""))
                _rewrite_property_hrefs(room, hotel_id, room_id, rate_id)
                _rewrite_property_hrefs(property_entry, hotel_id, room_id, rate_id)

            _apply_exp_prices(property_entry, check_in, check_out, prices[0])

        if log_type == "Search":
            properties = _exp_property_entries(result)
            _set_wrapped_properties(result, properties[:1])

        path = result.get("httpRequest", {}).get("path")
        if isinstance(path, str) and "/properties/" in path:
            result["httpRequest"]["path"] = _replace_path_property_id(path, hotel_id)

        apply_exp_supplier_currency(result, spec.supplier_currency)
        return result

    def propagate_package_linkage(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        room_names = normalized_room_names(spec)
        if room_names:
            for log_type in ("Search", "Packages", "PreBooking"):
                expectation = expectations_by_type.get(log_type)
                if isinstance(expectation, dict):
                    apply_exp_room_names(expectation, room_names)
        packages = expectations_by_type.get("Packages")
        prebook = expectations_by_type.get("PreBooking")
        if not packages or not prebook:
            return

        property_id, room_id, rate_id = _extract_exp_package_ids(packages)
        if not all((property_id, room_id, rate_id)):
            return

        token = _extract_primary_price_check_token(packages)
        prebook_path = build_exp_price_check_href(property_id, room_id, rate_id, token)
        prebook.setdefault("httpRequest", {})["path"] = prebook_path.split("?", 1)[0]

        price_check_href = build_exp_price_check_href(property_id, room_id, rate_id, token)
        for log_type in ("Search", "Packages"):
            expectation = expectations_by_type.get(log_type)
            if isinstance(expectation, dict):
                _set_price_check_hrefs(expectation, price_check_href)
                if log_type == "Search":
                    _align_search_room_rate_ids(expectation, room_id, rate_id)

    @property
    def log_types(self) -> list[str]:
        return LOG_TYPES


def _exp_property_entries(expectation: dict) -> list[dict]:
    body = expectation.get("httpResponse", {}).get("body")
    if isinstance(body, dict):
        properties = body.get("body")
        if isinstance(properties, list):
            return [entry for entry in properties if isinstance(entry, dict)]
    if isinstance(body, list):
        return [entry for entry in body if isinstance(entry, dict)]
    return []


def _set_wrapped_properties(expectation: dict, properties: list[dict]) -> None:
    body = expectation.get("httpResponse", {}).get("body")
    if isinstance(body, dict):
        body["body"] = properties
    elif isinstance(body, list):
        expectation.setdefault("httpResponse", {})["body"] = properties


def _ensure_distribution(rate: dict) -> None:
    sale_scenario = rate.setdefault("sale_scenario", {})
    if isinstance(sale_scenario, dict):
        sale_scenario["distribution"] = True


def _apply_exp_prices(node: dict, check_in: str, check_out: str, total_price: float) -> None:
    update_fields_recursive(
        node,
        {
            "netPrice": lambda _value: total_price,
            "totalPrice": lambda _value: total_price,
        },
    )
    for key in ("netPricePerNight", "totalPricePerNight"):
        if key in node and isinstance(node[key], dict):
            _fill_price_per_night(node[key], check_in, check_out, total_price)

    occupancy_pricing = node.get("occupancy_pricing")
    if isinstance(occupancy_pricing, dict):
        _resize_occupancy_nightly(occupancy_pricing, check_in, check_out)
        _apply_exp_occupancy_pricing(occupancy_pricing, total_price)


def _resize_occupancy_nightly(occupancy_pricing: dict, check_in: str, check_out: str) -> None:
    nights = _night_count(check_in, check_out)
    for occ_data in occupancy_pricing.values():
        if not isinstance(occ_data, dict):
            continue
        nightly = occ_data.get("nightly")
        if not isinstance(nightly, list) or not nightly:
            continue
        template_night = nightly[0]
        occ_data["nightly"] = [deep_copy(template_night) for _ in range(nights)]


def _apply_exp_occupancy_pricing(occupancy_pricing: dict, total_price: float) -> None:
    for occ_data in occupancy_pricing.values():
        if not isinstance(occ_data, dict):
            continue
        totals = occ_data.get("totals")
        if not isinstance(totals, dict):
            continue
        old_inclusive = _read_inclusive_total(totals)
        if old_inclusive is None or old_inclusive <= 0:
            continue
        ratio = total_price / old_inclusive
        _scale_exp_money_fields(occ_data, ratio)


def _set_price_check_hrefs(expectation: dict, href: str) -> None:
    for node in walk_nodes(expectation.get("httpResponse", {}).get("body")):
        if not isinstance(node, dict):
            continue
        links = node.get("links")
        if isinstance(links, dict):
            price_check = links.get("price_check")
            if isinstance(price_check, dict):
                price_check["href"] = href
        bed_groups = node.get("bed_groups")
        if isinstance(bed_groups, dict):
            for bed_group in bed_groups.values():
                if not isinstance(bed_group, dict):
                    continue
                bg_links = bed_group.get("links")
                if isinstance(bg_links, dict):
                    price_check = bg_links.get("price_check")
                    if isinstance(price_check, dict):
                        price_check["href"] = href


def _align_search_room_rate_ids(expectation: dict, room_id: str, rate_id: str) -> None:
    """Overwrite room/rate id fields in Search body to match Packages-extracted IDs.

    Search and Packages templates have different room/rate numeric IDs. The
    adapter matches rates by id field, so the Search body must agree with the
    ids embedded in price_check.href (which come from Packages).
    """
    for property_entry in _exp_property_entries(expectation):
        rooms = property_entry.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            continue
        room = rooms[0]
        if not isinstance(room, dict):
            continue
        room["id"] = room_id
        rates = room.get("rates")
        if not isinstance(rates, list):
            continue
        for rate in rates:
            if isinstance(rate, dict):
                rate["id"] = rate_id


def _strip_non_standard_exp_occ_fields(rate: dict) -> None:
    """Remove fields present in ingested templates but absent in real EXP API.

    Real EXP occupancy_pricing has only: nightly, totals.
    Templates may carry stay, fees (ingested from older SIDs) and
    property_fees inside totals. The EXP adapter doesn't produce these,
    so keeping them causes incorrect price sums / parse failures.
    Search rates also carry marketing_fee_incentives which real EXP omits.
    """
    rate.pop("marketing_fee_incentives", None)
    occ = rate.get("occupancy_pricing")
    if not isinstance(occ, dict):
        return
    for occ_data in occ.values():
        if not isinstance(occ_data, dict):
            continue
        occ_data.pop("stay", None)
        occ_data.pop("fees", None)
        totals = occ_data.get("totals")
        if isinstance(totals, dict):
            totals.pop("property_fees", None)


def _trim_bed_groups(rate: dict) -> None:
    bed_groups = rate.get("bed_groups")
    if not isinstance(bed_groups, dict) or not bed_groups:
        return
    first_key = next(iter(bed_groups))
    kept = bed_groups[first_key]
    if isinstance(kept, dict):
        kept["description"] = "1 Bed"
    rate["bed_groups"] = {first_key: kept}


def _rename_occupancy_key(rate: dict, target_key: str) -> None:
    """Rename occupancy_pricing keys to match actual search adult count.

    EAN returns occupancy_pricing keyed by adult count (e.g. "2" for 2 adults).
    Templates are ingested from reference SIDs that may use "1"; the search
    in core_app.py hardcodes 2 adults, so the mock key must be "2".
    """
    occ = rate.get("occupancy_pricing")
    if not isinstance(occ, dict) or target_key in occ:
        return
    keys = [k for k in occ if k != target_key]
    if keys:
        occ[target_key] = occ.pop(keys[0])


def _extract_primary_price_check_token(packages: dict) -> str:
    for property_entry in _exp_property_entries(packages):
        rooms = property_entry.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            continue
        rates = rooms[0].get("rates") if isinstance(rooms[0], dict) else None
        if not isinstance(rates, list) or not rates:
            continue
        rate = rates[0]
        bed_groups = rate.get("bed_groups") if isinstance(rate, dict) else None
        if isinstance(bed_groups, dict):
            for bed_group in bed_groups.values():
                if not isinstance(bed_group, dict):
                    continue
                href = bed_group.get("links", {}).get("price_check", {}).get("href")
                token = extract_price_check_token(href) if isinstance(href, str) else ""
                if token:
                    return token
    return ""


def _rewrite_property_hrefs(
    node: dict,
    hotel_id: str,
    room_id: str,
    rate_id: str,
) -> None:
    for item in walk_nodes(node):
        if not isinstance(item, dict):
            continue
        href = item.get("href")
        if not isinstance(href, str) or "/v3/properties/" not in href:
            continue
        updated = _PROPERTY_HREF_RE.sub(f"/v3/properties/{hotel_id}", href)
        if room_id:
            updated = re.sub(r"/rooms/\d+", f"/rooms/{room_id}", updated)
        if rate_id:
            updated = re.sub(r"/rates/\d+", f"/rates/{rate_id}", updated)
        item["href"] = updated


def _night_count(check_in: str, check_out: str) -> int:
    start = datetime.strptime(check_in, "%Y-%m-%d")
    end = datetime.strptime(check_out, "%Y-%m-%d")
    return max((end - start).days, 1)


def _read_inclusive_total(totals: dict) -> float | None:
    inclusive = totals.get("inclusive")
    if not isinstance(inclusive, dict):
        return None
    request_currency = inclusive.get("request_currency")
    if isinstance(request_currency, dict):
        return _parse_money(request_currency.get("value"))
    return None


def _parse_money(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _format_money(amount: float) -> str:
    return f"{amount:.2f}"


def _scale_exp_money_fields(node: object, ratio: float) -> None:
    if isinstance(node, dict):
        if "value" in node and "currency" in node:
            parsed = _parse_money(node.get("value"))
            if parsed is not None:
                node["value"] = _format_money(parsed * ratio)
        for value in node.values():
            _scale_exp_money_fields(value, ratio)
    elif isinstance(node, list):
        for item in node:
            _scale_exp_money_fields(item, ratio)


def _fill_price_per_night(price_map: dict, check_in: str, check_out: str, total_price: float) -> None:
    nights = _night_count(check_in, check_out)
    per_night = round(total_price / nights, 2)
    price_map.clear()
    start = datetime.strptime(check_in, "%Y-%m-%d")
    for offset in range(nights):
        current = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        price_map[current] = per_night


def _normalized_refundable(spec: PackageSpec) -> list[bool]:
    flags = list(spec.refundable)
    while len(flags) < spec.count:
        flags.append(False)
    return flags[: spec.count]


def _normalized_prices(spec: PackageSpec) -> list[float]:
    prices = list(spec.prices)
    while len(prices) < spec.count:
        prices.append(prices[-1] if prices else 0.0)
    return prices[: spec.count]


def _replace_primary_property_id(url: str, hotel_id: str) -> str:
    if re.search(r"property_id=[^&]+", url):
        return re.sub(r"property_id=[^&]+", f"property_id={hotel_id}", url, count=1)
    return url


def _replace_path_property_id(path: str, hotel_id: str) -> str:
    parts = path.split("/")
    for index, part in enumerate(parts):
        if part == "properties" and index + 1 < len(parts):
            parts[index + 1] = str(hotel_id)
            break
    return "/".join(parts)


def _extract_exp_package_ids(packages: dict) -> tuple[str | None, str | None, str | None]:
    properties = _exp_property_entries(packages)
    if not properties:
        return None, None, None
    property_entry = properties[0]
    property_id = str(property_entry.get("property_id", "")) or None
    rooms = property_entry.get("rooms")
    if not isinstance(rooms, list) or not rooms:
        return property_id, None, None
    room = rooms[0]
    if not isinstance(room, dict):
        return property_id, None, None
    room_id = str(room.get("id", "")) or None
    rates = room.get("rates")
    if not isinstance(rates, list) or not rates:
        return property_id, room_id, None
    rate = rates[0]
    if not isinstance(rate, dict):
        return property_id, room_id, None
    rate_id = str(rate.get("id", "")) or None
    return property_id, room_id, rate_id
