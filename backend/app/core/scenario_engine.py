"""Load templates, apply mutations, validate linkage."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.booking_id_injector import BOOKING_FLOW_LOG_TYPES
from app.core.expectation_utils import finalize_expectation_for_register
from app.core.crawla_mutations import apply_supplier_mutation
from app.core.linkage_validator import LinkageValidator
from app.core.namespace import apply_namespace
from app.ingest.expectation_builder import OPTIONAL_TEMPLATE_LOG_TYPES
from app.models.scenario import ScenarioRequest
from app.plugins import PLUGINS

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "templates"

PACKAGE_MUTABLE_LOG_TYPES = {
    "HBS": {"Search", "Packages"},
    "EXP": {"Search", "Packages"},
    "RHK": {"Search", "Packages"},
    "CHC": {"Search", "Packages", "PreBooking", "GetOrder"},
    "EXT": {"Search", "Packages"},
}

# All SMF searches run 2 adults (see CoreAppClient search payload). Supplier
# templates were ingested at differing occupancies (HBS/RHK=1, EXT/CHC=2), and
# adapters drop packages whose occupancy != the request — so a 2-adult search
# silently returns nothing for a 1-adult mock (this is why EXT dropped out of the
# SB search). Normalize every supplier's Search/Packages mock to the same adult
# count. TODO: make this configurable from the UI (per-scenario occupancy).
SEARCH_ADULTS = 2
_ADULT_OCCUPANCY_KEYS = frozenset(
    {"adults", "adultCount", "adultsCount", "numberAdults", "numberOfAdults", "requestedNumberAdults"}
)
_OCCUPANCY_NORMALIZED_LOG_TYPES = frozenset({"Search", "Packages"})


def _force_adult_occupancy(node: object, adults: int) -> None:
    """Recursively set adult-count occupancy fields to `adults`, preserving each
    field's int/str type. Children/other fields are left untouched."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key in _ADULT_OCCUPANCY_KEYS
                and isinstance(value, (int, str))
                and not isinstance(value, bool)
            ):
                node[key] = type(value)(adults)
            else:
                _force_adult_occupancy(value, adults)
    elif isinstance(node, list):
        for item in node:
            _force_adult_occupancy(item, adults)


@dataclass
class BuiltExpectation:
    supplier_code: str
    log_type: str
    expectation: dict
    # Identifies WHICH entry of this supplier code the expectation belongs to.
    # Equals supplier_code for the first (usually only) instance.
    instance_key: str = ""

    def __post_init__(self) -> None:
        if not self.instance_key:
            self.instance_key = self.supplier_code


class ScenarioEngine:
    def __init__(
        self,
        templates_dir: Path | None = None,
        linkage_validator: LinkageValidator | None = None,
    ) -> None:
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self.linkage_validator = linkage_validator or LinkageValidator()

    def build_expectations(self, request: ScenarioRequest) -> list[BuiltExpectation]:
        built: list[BuiltExpectation] = []
        for supplier_scenario in request.suppliers:
            supplier_code = supplier_scenario.code.value
            instance_key = supplier_scenario.instance_key
            plugin = PLUGINS[supplier_code]
            # When no package is selected for the booking flow, only build
            # search/package (+ prebooking/cancellation-policy) mocks — skip
            # Booking/GetOrder/CancelOrder entirely for this supplier.
            log_types = plugin.log_types
            if supplier_scenario.packages.booking_package_index is None:
                log_types = [lt for lt in log_types if lt not in BOOKING_FLOW_LOG_TYPES]
            templates = self._load_supplier_templates(supplier_code, log_types)
            mutated = self._mutate_supplier_templates(
                plugin=plugin,
                templates=templates,
                request=request,
                package_spec=supplier_scenario.packages,
                supplier_scenario=supplier_scenario,
            )
            validation_spec = supplier_scenario.packages
            supplier_mutation = request.mutation_for(supplier_scenario)
            if supplier_mutation and supplier_mutation.room_basis:
                # model_copy() bypasses validators, so build the per-package list
                # explicitly rather than relying on PackageSpec's str-coercion.
                validation_spec = validation_spec.model_copy(
                    update={"room_basis": [supplier_mutation.room_basis] * validation_spec.count}
                )
            # Skip linkage validation when the hotel is intentionally excluded from
            # the supplier response (e.g. ONLY_CRAWLA — EXP hotel stripped out).
            # There are no rates to validate in that case.
            if not (supplier_mutation and supplier_mutation.exclude_hotel):
                self.linkage_validator.validate(
                    mutated,
                    supplier_code,
                    validation_spec,
                )
            for log_type, expectation in mutated.items():
                built.append(
                    BuiltExpectation(
                        supplier_code=supplier_code,
                        instance_key=instance_key,
                        log_type=log_type,
                        expectation=finalize_expectation_for_register(
                            expectation,
                            request.namespace,
                            supplier_code,
                            log_type,
                            instance_key=instance_key,
                        ),
                    )
                )
        return built

    def _load_supplier_templates(self, supplier_code: str, log_types: list[str]) -> dict[str, dict]:
        templates: dict[str, dict] = {}
        supplier_dir = self.templates_dir / supplier_code
        if not supplier_dir.exists():
            raise FileNotFoundError(f"Templates not found for supplier {supplier_code}")

        for log_type in log_types:
            if log_type in OPTIONAL_TEMPLATE_LOG_TYPES:
                path = supplier_dir / log_type / "v1.json"
                if not path.exists():
                    continue
            else:
                path = supplier_dir / log_type / "v1.json"
                if not path.exists():
                    raise FileNotFoundError(
                        f"Missing required template: {supplier_code}/{log_type}/v1.json"
                    )
            templates[log_type] = json.loads(path.read_text(encoding="utf-8"))
        return templates

    def _mutate_supplier_templates(
        self,
        plugin,
        templates: dict[str, dict],
        request: ScenarioRequest,
        package_spec,
        supplier_scenario=None,
    ) -> dict[str, dict]:
        mutated: dict[str, dict] = {}
        # Mutations are addressed per supplier ENTRY: with the same supplier added
        # twice, looking them up by bare code would hand both instances the same
        # mutation. Falls back to the code for the first instance.
        supplier_mutation = (
            request.mutation_for(supplier_scenario)
            if supplier_scenario is not None
            else request.supplier_mutations.get(plugin.code)
        )
        instance_key = supplier_scenario.instance_key if supplier_scenario is not None else plugin.code
        package_log_types = PACKAGE_MUTABLE_LOG_TYPES.get(plugin.code, {"Packages"})

        for log_type, template in templates.items():
            expectation = copy.deepcopy(template)
            expectation = plugin.mutate_dates(expectation, request.check_in, request.check_out)
            if log_type in package_log_types:
                expectation = plugin.mutate_packages(
                    expectation,
                    package_spec,
                    request.hotel_id_for_supplier(plugin.code),
                    request.check_in,
                    request.check_out,
                    log_type,
                )
            mutated[log_type] = expectation

        plugin.propagate_package_linkage(mutated, package_spec)
        for log_type, expectation in mutated.items():
            mutated[log_type] = apply_namespace(
                expectation,
                request.namespace,
                instance_key,
                log_type,
            )
            mutated[log_type] = apply_supplier_mutation(
                mutated[log_type],
                plugin.code,
                log_type,
                request.hotel_id_for_supplier(plugin.code),
                supplier_mutation,
            )
            if log_type in _OCCUPANCY_NORMALIZED_LOG_TYPES:
                body = mutated[log_type].get("httpResponse", {}).get("body")
                _force_adult_occupancy(body, SEARCH_ADULTS)
        return mutated
