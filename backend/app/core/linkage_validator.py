"""Ensure search/package/prebook identifiers stay consistent after mutations."""

from __future__ import annotations

from app.models.scenario import PackageSpec
from app.plugins.json_utils import collect_field_values
from app.plugins.room_names import normalized_room_basis


class LinkageError(ValueError):
    pass


def _derby_bts_codes() -> frozenset[str]:
    """Codes behind hotels-derby-bts-adapter — same payload, so same validation.

    Read off the plugin registry rather than restated here, so registering another Derby
    supplier can't leave this list behind. Imported lazily to keep app.plugins off the
    import path of a module it does not otherwise need.
    """
    from app.plugins import PLUGINS, DerbyBtsMockPlugin

    return frozenset(
        code for code, plugin in PLUGINS.items() if isinstance(plugin, DerbyBtsMockPlugin)
    )


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
        elif supplier_code in _derby_bts_codes():
            self._validate_derby_bts(expectations_by_type, supplier_code, spec)
        elif supplier_code == "EXT":
            self._validate_ext(expectations_by_type, spec)
        else:
            # A supplier added from the Suppliers screen has no hand-written rule —
            # validate what its mutation config describes rather than refusing to
            # build the scenario at all.
            self._validate_generic(expectations_by_type, supplier_code, spec)

    def _validate_generic(
        self,
        expectations_by_type: dict[str, dict],
        supplier_code: str,
        spec: PackageSpec,
    ) -> None:
        """Rate count, and board when the supplier declares a board key."""
        from app.core.path_utils import resolve_path
        from app.services.supplier_service import UnknownSupplierError, get_supplier_config

        packages = expectations_by_type.get("Packages")
        if packages is None:
            raise LinkageError(f"{supplier_code} Packages template missing")

        try:
            config = get_supplier_config(supplier_code)
        except UnknownSupplierError as exc:
            raise LinkageError(str(exc)) from exc

        mutation = config.mutation_config
        if not mutation.packages_path:
            raise LinkageError(
                f"{supplier_code} has no packages path configured — cannot verify that "
                f"{spec.count} packages were produced. Set one on the Suppliers screen."
            )

        rates = resolve_path(packages, mutation.packages_path)
        if not isinstance(rates, list):
            raise LinkageError(
                f"{supplier_code} packages path {mutation.packages_path!r} does not "
                "point at an array in the Packages template"
            )
        if len(rates) < spec.count:
            raise LinkageError(
                f"{supplier_code} package rate count {len(rates)} < requested {spec.count}"
            )

        if not mutation.board_key:
            return
        expected_boards = normalized_room_basis(spec)
        for index, rate in enumerate(rates[: spec.count]):
            if not isinstance(rate, dict):
                continue
            board = rate.get(mutation.board_key)
            if board and str(board) != expected_boards[index]:
                raise LinkageError(
                    f"{supplier_code} package {mutation.board_key} does not match requested room_basis"
                )

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
        expected_boards = normalized_room_basis(spec)
        if board_codes and any(
            code != expected_boards[index] for index, code in enumerate(board_codes[: spec.count])
        ):
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

        expected_meals = [_rhk_meal_for_basis(basis) for basis in normalized_room_basis(spec)]
        for index, rate in enumerate(rates[: spec.count]):
            meal = rate.get("meal")
            if meal and meal != expected_meals[index]:
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


    def _validate_derby_bts(
        self,
        expectations_by_type: dict[str, dict],
        supplier_code: str,
        spec: PackageSpec,
    ) -> None:
        """Shared by every supplier behind hotels-derby-bts-adapter (CHC, HIL)."""
        packages = expectations_by_type.get("Packages")
        if packages is None:
            raise LinkageError(f"{supplier_code} Packages template missing")

        rates = _derby_bts_package_rates(packages)
        if len(rates) < spec.count:
            raise LinkageError(
                f"{supplier_code} package rate count {len(rates)} < requested {spec.count}"
            )

        expected_meals = normalized_room_basis(spec)
        for index, rate in enumerate(rates[: spec.count]):
            meal = rate.get("mealPlan")
            if meal and meal != expected_meals[index]:
                raise LinkageError(
                    f"{supplier_code} package mealPlan does not match requested room_basis"
                )

    def _validate_ext(self, expectations_by_type: dict[str, dict], spec: PackageSpec) -> None:
        packages = expectations_by_type.get("Packages")
        if packages is None:
            raise LinkageError("EXT Packages template missing")

        accommodations = _ext_package_rates(packages)
        if len(accommodations) < spec.count:
            raise LinkageError(
                f"EXT accommodation count {len(accommodations)} < requested {spec.count}"
            )

        expected_meals = normalized_room_basis(spec)
        for index, accommodation in enumerate(accommodations[: spec.count]):
            # EXT stores board in distributions[0]
            distributions = accommodation.get("distributions", [])
            if distributions and isinstance(distributions[0], dict):
                meal = distributions[0].get("board")
                if meal and meal != expected_meals[index]:
                    raise LinkageError("EXT accommodation board does not match requested room_basis")


def _derby_bts_package_rates(packages: dict) -> list[dict]:
    body = packages.get("httpResponse", {}).get("body", {})
    rates = body.get("roomRates") if isinstance(body, dict) else None
    return [rate for rate in rates if isinstance(rate, dict)] if isinstance(rates, list) else []


def _ext_package_rates(packages: dict) -> list[dict]:
    """Extract distributions from EXT Packages response (accommodations with distributions).

    EXT structure: body.body[].accommodations[] (one per package count).
    Each accommodation has distributions[], but we validate by accommodation count.
    """
    body = packages.get("httpResponse", {}).get("body", {})
    if not isinstance(body, dict):
        return []

    # EXT structure: body.body[].accommodations[]
    body_list = body.get("body")
    if not isinstance(body_list, list) or not body_list:
        return []

    hotel = body_list[0]
    if not isinstance(hotel, dict):
        return []

    accommodations = hotel.get("accommodations")
    if not isinstance(accommodations, list):
        return []

    # Return accommodations as "rates" — one accommodation per package
    return [acc for acc in accommodations if isinstance(acc, dict)]


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
