"""Config-driven mock plugin — what a supplier added from the UI uses.

Every hand-written plugin does the same four things: retarget the dates, point the
payload at the requested hotel, clone the first rate/room/accommodation up to the
requested package count, and stamp price / board / room name / currency onto each
clone. This does exactly that, reading the key names and the array location from the
supplier's ``mutation_config`` instead of hardcoding them.

It is a fallback, not a replacement: ``resolve_plugin`` prefers a hand-written plugin
whenever one exists, because real payloads have quirks config can't express (EXP's
per-night price maps, RHK's meal-code vocabulary, HBS's rateKey linkage).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.path_utils import resolve_parent, resolve_path
from app.models.scenario import PackageSpec
from app.models.supplier import MutationConfig
from app.plugins.base import SupplierMockPlugin
from app.plugins.json_utils import deep_copy, update_fields_recursive
from app.plugins.room_names import normalized_room_basis


def normalized_prices(spec: PackageSpec) -> list[float]:
    """Prices padded to ``spec.count`` by repeating the last value."""
    prices = list(spec.prices)
    while len(prices) < spec.count:
        prices.append(prices[-1] if prices else 0.0)
    return prices[: spec.count]


def normalized_refundable(spec: PackageSpec) -> list[bool]:
    """Refundable flags padded to ``spec.count`` with False."""
    flags = list(spec.refundable)
    while len(flags) < spec.count:
        flags.append(False)
    return flags[: spec.count]


def normalized_room_names(spec: PackageSpec) -> list[str]:
    names = list(spec.room_names)
    while len(names) < spec.count:
        names.append(names[-1] if names else "")
    return names[: spec.count]


class GenericMockPlugin(SupplierMockPlugin):
    def __init__(self, code: str, mutation_config: MutationConfig, log_types: list[str]) -> None:
        self.code = code
        self.config = mutation_config
        self._log_types = list(log_types)

    # ── SupplierMockPlugin ──────────────────────────────────────────────────────

    @property
    def log_types(self) -> list[str]:
        return self._log_types

    def matches_adapter_source(self, source: str) -> bool:
        match = self.config.adapter_source_match
        if not match:
            return False
        return match.lower() in source.lower()

    def mutate_dates(self, expectation: dict, check_in: str, check_out: str) -> dict:
        result = deep_copy(expectation)
        updates: dict[str, Any] = {}
        for key in self.config.check_in_keys:
            updates[key] = lambda _value, v=check_in: v
        for key in self.config.check_out_keys:
            updates[key] = lambda _value, v=check_out: v
        if updates:
            update_fields_recursive(result, updates)
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
        result = self.mutate_dates(expectation, check_in, check_out)

        if hotel_id and self.config.hotel_id_key:
            update_fields_recursive(
                result, {self.config.hotel_id_key: lambda _value, v=hotel_id: v}
            )

        packages = resolve_path(result, self.config.packages_path)
        if not isinstance(packages, list) or not packages:
            # Nothing to clone — dates and hotel id still applied. Readiness flags a
            # missing/wrong packages_path before it gets this far.
            return result

        template = deep_copy(packages[0])
        prices = normalized_prices(spec)
        refundable = normalized_refundable(spec)
        room_names = normalized_room_names(spec)
        boards = self._boards(spec)

        clones = []
        for index in range(spec.count):
            clone = deep_copy(template)
            self._apply_row(clone, prices[index], boards[index], room_names[index], refundable[index], spec)
            clones.append(clone)

        parent, key = resolve_parent(result, self.config.packages_path)
        if parent is not None and key is not None:
            parent[key] = clones
        return result

    def propagate_package_linkage(
        self,
        expectations_by_type: dict[str, dict],
        spec: PackageSpec,
    ) -> None:
        """No-op: with generated package ids there is nothing to keep in sync.

        A supplier whose prebook/book flow echoes an id from the packages response
        needs a hand-written plugin for that step.
        """

    # ── internals ───────────────────────────────────────────────────────────────

    def _boards(self, spec: PackageSpec) -> list[str]:
        boards = normalized_room_basis(spec)
        allowed = self.config.board_values
        if not allowed:
            return boards
        fallback = allowed[0]
        return [b if b.upper() in {a.upper() for a in allowed} else fallback for b in boards]

    def _apply_row(
        self,
        clone: dict,
        price: float,
        board: str,
        room_name: str,
        refundable: bool,
        spec: PackageSpec,
    ) -> None:
        updates: dict[str, Any] = {}
        for key in self.config.price_keys:
            updates[key] = lambda _value, v=price: v
        if self.config.board_key:
            updates[self.config.board_key] = lambda _value, v=board: v
        if self.config.room_name_key:
            updates[self.config.room_name_key] = lambda _value, v=room_name: v
        if self.config.currency_key:
            updates[self.config.currency_key] = lambda _value, v=spec.supplier_currency: v
        if self.config.refundable_key:
            updates[self.config.refundable_key] = lambda _value, v=refundable: v
        if self.config.package_id_key:
            # A fresh id per clone, or every package shares the template's id and the
            # adapter collapses them into one.
            updates[self.config.package_id_key] = lambda _value: str(uuid.uuid4())
        if updates:
            update_fields_recursive(clone, updates)
