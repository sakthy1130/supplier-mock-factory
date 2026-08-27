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
from app.models.scenario import PreBookingStatus, ScenarioRequest
from app.plugins import resolve_plugin

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "templates"


def _template_filename(log_type: str, prebooking_status: PreBookingStatus) -> str:
    """The template file for this log type — a status variant only for PreBooking.

    `available` maps to the historical v1.json, so every existing scenario keeps
    loading exactly the file it always did.
    """
    if log_type == "PreBooking" and prebooking_status is not PreBookingStatus.available:
        return f"{prebooking_status.value}.json"
    return "v1.json"


def _reject_explicit_pricing_for_net_supplier(supplier_code: str) -> None:
    """Raise if this env prices `supplier_code` net — the gross split cannot apply.

    An unknown supplier is left alone: resolve_plugin/_package_log_types already report
    that far more usefully than a pricing complaint would.
    """
    from app.env_context import get_current_env
    from app.services.supplier_service import UnknownSupplierError, get_supplier_config

    try:
        config = get_supplier_config(supplier_code)
    except UnknownSupplierError:
        return
    if config.supplier_type == "net":
        env = get_current_env()
        raise ValueError(
            f"{supplier_code} is a net supplier on '{env}', so originalPriceWithVAT and "
            "markup do not apply — that split only exists for a gross supplier, where "
            "the markup sits inside the total. Send the package price alone."
        )


def _package_log_types(supplier_code: str) -> set[str]:
    """Log types whose response body gets package mutation for this supplier.

    Defaults to Packages only — a supplier that also serves rates on Search (or, for
    CHC, on PreBooking/GetOrder) declares that on its config.
    """
    from app.services.supplier_service import UnknownSupplierError, get_supplier_config

    try:
        return set(get_supplier_config(supplier_code).package_log_types) or {"Packages"}
    except UnknownSupplierError:
        return {"Packages"}

# Supplier templates were ingested at differing occupancies (HBS/RHK=1, EXT/CHC=2),
# and adapters drop packages whose occupancy != the request — so a 2-adult search
# silently returns nothing for a 1-adult mock (this is why EXT dropped out of the SB
# search). Every Search/Packages mock is normalized to the scenario's adult count.
#
# The count now comes from PackageSpec.adults, which defaults to 2 — the occupancy
# every SMF search runs (see CoreAppClient search payload). This is the per-scenario
# occupancy the constant here used to stand in for.
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
            supplier_code = str(supplier_scenario.code)
            instance_key = supplier_scenario.instance_key
            # From the suppliers table, not a hardcoded registry: a supplier added from
            # the Suppliers screen gets the generic mutator built from its own config.
            plugin = resolve_plugin(supplier_code)
            # The originalPriceWithVAT/markup split only means something for a GROSS
            # supplier: the markup sits inside totals.inclusive and these fields say how
            # to divide it. A net supplier carries no such markup node, so accepting the
            # values would write a split the contract cannot express. supplier_type is
            # per-env (EXP is gross on dev/stg, net on ODIS), so this is resolved from
            # the suppliers table rather than the code.
            if supplier_scenario.packages.has_explicit_pricing:
                _reject_explicit_pricing_for_net_supplier(supplier_code)
            # When no package is selected for the booking flow, only build
            # search/package (+ prebooking/cancellation-policy) mocks — skip
            # Booking/GetOrder/CancelOrder entirely for this supplier.
            log_types = plugin.log_types
            spec = supplier_scenario.packages
            # sold_out stops the chain at PreBooking: that body carries no links.book,
            # so the core cannot proceed to booking even if the mocks existed. Same set
            # already dropped when no package is selected for booking.
            sold_out = spec.prebooking_status is PreBookingStatus.sold_out
            if spec.booking_package_index is None or sold_out:
                log_types = [lt for lt in log_types if lt not in BOOKING_FLOW_LOG_TYPES]

            templates = self._load_supplier_templates(
                supplier_code, log_types, spec.prebooking_status
            )
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

    def _load_supplier_templates(
        self,
        supplier_code: str,
        log_types: list[str],
        prebooking_status: PreBookingStatus = PreBookingStatus.available,
    ) -> dict[str, dict]:
        templates: dict[str, dict] = {}
        supplier_dir = self.templates_dir / supplier_code
        if not supplier_dir.exists():
            raise FileNotFoundError(f"Templates not found for supplier {supplier_code}")

        for log_type in log_types:
            filename = _template_filename(log_type, prebooking_status)
            path = supplier_dir / log_type / filename
            if not path.exists():
                if log_type in OPTIONAL_TEMPLATE_LOG_TYPES:
                    continue
                # Never silently fall back to v1.json for a requested status — the
                # scenario would provision an 'available' mock while reporting the
                # status the caller asked for, which is worse than failing.
                raise FileNotFoundError(
                    f"Missing required template: {supplier_code}/{log_type}/{filename}"
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
        # PACKAGE_MUTABLE_LOG_TYPES was a hardcoded per-code map; the suppliers table
        # owns this now, so a UI-added supplier declares its own mutable log types.
        package_log_types = _package_log_types(plugin.code)

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
                _force_adult_occupancy(body, package_spec.adults)
        return mutated
