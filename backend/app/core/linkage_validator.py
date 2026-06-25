"""Ensure search/package/prebook identifiers stay consistent after mutations."""

from __future__ import annotations

from app.models.scenario import PackageSpec
from app.plugins.json_utils import collect_field_values


class LinkageError(ValueError):
    pass


class LinkageValidator:
    def validate(
        self,
        expectations_by_type: dict[str, dict],
        supplier_code: str,
        spec: PackageSpec,
    ) -> None:
        if supplier_code == "HBS":
            self._validate_hbs(expectations_by_type, spec)
        elif supplier_code == "EXP":
            self._validate_exp(expectations_by_type, spec)
        elif supplier_code == "RHK":
            self._validate_rhk(expectations_by_type, spec)
        elif supplier_code == "CHC":
            self._validate_chc(expectations_by_type, spec)
        else:
            raise LinkageError(f"Unsupported supplier for linkage validation: {supplier_code}")

    def _validate_hbs(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        packages = expectations_by_type.get("Packages")
        prebook = expectations_by_type.get("PreBooking")
        if packages is None:
            raise LinkageError("HBS Packages template missing")

        package_rate_keys = collect_field_values(
            packages.get("httpResponse", {}).get("body", {}),
            "rateKey",
        )
        if len(package_rate_keys) < spec.count:
            raise LinkageError(
                f"HBS package rate count {len(package_rate_keys)} < requested {spec.count}"
            )

        board_codes = collect_field_values(
            packages.get("httpResponse", {}).get("body", {}),
            "boardCode",
        )
        if board_codes and any(code != spec.room_basis for code in board_codes[: spec.count]):
            raise LinkageError("HBS package boardCode does not match requested room_basis")

        if prebook is not None:
            request_json = (
                prebook.get("httpRequest", {}).get("body", {}).get("json")
                if isinstance(prebook.get("httpRequest", {}).get("body"), dict)
                else None
            )
            prebook_rate_keys = (
                collect_field_values(request_json, "rateKey")
                if isinstance(request_json, dict)
                else []
            )
            if prebook_rate_keys and package_rate_keys[0] not in prebook_rate_keys:
                raise LinkageError("HBS PreBooking rateKey does not match Packages primary rateKey")

    def _validate_exp(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        packages = expectations_by_type.get("Packages")
        prebook = expectations_by_type.get("PreBooking")
        if packages is None:
            raise LinkageError("EXP Packages template missing")

        rates = _exp_package_rates(packages)
        if len(rates) < spec.count:
            raise LinkageError(
                f"EXP package rate count {len(rates)} < requested {spec.count}"
            )

        for index, rate in enumerate(rates[: spec.count]):
            if "refundable" in rate and len(spec.refundable) > index:
                expected = spec.refundable[index]
                if bool(rate.get("refundable")) != expected:
                    raise LinkageError(
                        f"EXP package refundable flag at index {index} does not match spec"
                    )

        if prebook is not None:
            property_id, room_id, rate_id = _parse_exp_prebook_path(prebook)
            pkg_property_id, pkg_room_id, pkg_rate_id = _parse_exp_package_ids(packages)
            if property_id and pkg_property_id and property_id != pkg_property_id:
                raise LinkageError("EXP PreBooking property_id does not match Packages")
            if room_id and pkg_room_id and room_id != pkg_room_id:
                raise LinkageError("EXP PreBooking room_id does not match Packages")
            if rate_id and pkg_rate_id and rate_id != pkg_rate_id:
                raise LinkageError("EXP PreBooking rate_id does not match Packages")

    def _validate_rhk(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        packages = expectations_by_type.get("Packages")
        prebook = expectations_by_type.get("PreBooking")
        if packages is None:
            raise LinkageError("RHK Packages template missing")

        rates = _rhk_package_rates(packages)
        if len(rates) < spec.count:
            raise LinkageError(
                f"RHK package rate count {len(rates)} < requested {spec.count}"
            )

        expected_meal = _rhk_meal_for_basis(spec.room_basis)
        for index, rate in enumerate(rates[: spec.count]):
            meal = rate.get("meal")
            if meal and meal != expected_meal:
                raise LinkageError("RHK package meal does not match requested room_basis")
            if "refundable" in rate and len(spec.refundable) > index:
                expected = spec.refundable[index]
                if bool(rate.get("refundable")) != expected:
                    raise LinkageError(
                        f"RHK package refundable flag at index {index} does not match spec"
                    )

        if prebook is not None and rates:
            primary_hash = rates[0].get("match_hash")
            prebook_hashes = collect_field_values(prebook, "match_hash")
            if primary_hash and prebook_hashes and primary_hash not in prebook_hashes:
                raise LinkageError("RHK PreBooking match_hash does not match Packages primary match_hash")


    def _validate_chc(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        packages = expectations_by_type.get("Packages")
        if packages is None:
            raise LinkageError("CHC Packages template missing")

        rates = _chc_package_rates(packages)
        if len(rates) < spec.count:
            raise LinkageError(
                f"CHC package rate count {len(rates)} < requested {spec.count}"
            )

        expected_meal = spec.room_basis.upper()
        for rate in rates[: spec.count]:
            meal = rate.get("mealPlan")
            if meal and meal != expected_meal:
                raise LinkageError("CHC package mealPlan does not match requested room_basis")


def _chc_package_rates(packages: dict) -> list[dict]:
    body = packages.get("httpResponse", {}).get("body", {})
    rates = body.get("roomRates") if isinstance(body, dict) else None
    return [rate for rate in rates if isinstance(rate, dict)] if isinstance(rates, list) else []


def _rhk_meal_for_basis(room_basis: str) -> str:
    mapping = {
        "RO": "nomeal",
        "BB": "breakfast",
        "HB": "halfboard",
        "FB": "fullboard",
        "AI": "allinclusive",
    }
    return mapping.get(room_basis.upper(), "nomeal")


def _rhk_package_rates(packages: dict) -> list[dict]:
    body = packages.get("httpResponse", {}).get("body", {})
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return []
    hotels = data.get("hotels")
    if not isinstance(hotels, list) or not hotels:
        return []
    rates = hotels[0].get("rates") if isinstance(hotels[0], dict) else None
    return rates if isinstance(rates, list) else []


def _exp_package_rates(packages: dict) -> list[dict]:
    body = packages.get("httpResponse", {}).get("body", {})
    properties = body.get("body") if isinstance(body, dict) else None
    if not isinstance(properties, list) or not properties:
        return []
    rooms = properties[0].get("rooms") if isinstance(properties[0], dict) else None
    if not isinstance(rooms, list) or not rooms:
        return []
    package_rates: list[dict] = []
    for room in rooms:
        rates = room.get("rates") if isinstance(room, dict) else None
        if isinstance(rates, list):
            package_rates.extend(rate for rate in rates if isinstance(rate, dict))
    return package_rates


def _parse_exp_package_ids(packages: dict) -> tuple[str | None, str | None, str | None]:
    rates = _exp_package_rates(packages)
    body = packages.get("httpResponse", {}).get("body", {})
    properties = body.get("body") if isinstance(body, dict) else None
    if not isinstance(properties, list) or not properties:
        return None, None, None
    property_id = str(properties[0].get("property_id", "")) or None
    rooms = properties[0].get("rooms")
    if not isinstance(rooms, list) or not rooms:
        return property_id, None, None
    room_id = str(rooms[0].get("id", "")) or None
    rate_id = str(rates[0].get("id", "")) if rates else None
    return property_id, room_id, rate_id


def _parse_exp_prebook_path(prebook: dict) -> tuple[str | None, str | None, str | None]:
    path = prebook.get("httpRequest", {}).get("path")
    if not isinstance(path, str):
        return None, None, None
    parts = path.strip("/").split("/")
    try:
        properties_index = parts.index("properties")
        return parts[properties_index + 1], parts[properties_index + 3], parts[properties_index + 5]
    except (ValueError, IndexError):
        return None, None, None
