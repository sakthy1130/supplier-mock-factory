"""Load templates, apply mutations, validate linkage."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

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
}


@dataclass
class BuiltExpectation:
    supplier_code: str
    log_type: str
    expectation: dict


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
            plugin = PLUGINS[supplier_code]
            templates = self._load_supplier_templates(supplier_code, plugin.log_types)
            mutated = self._mutate_supplier_templates(
                plugin=plugin,
                templates=templates,
                request=request,
                package_spec=supplier_scenario.packages,
            )
            validation_spec = supplier_scenario.packages
            supplier_mutation = request.supplier_mutations.get(supplier_code)
            if supplier_mutation and supplier_mutation.room_basis:
                validation_spec = validation_spec.model_copy(update={"room_basis": supplier_mutation.room_basis})
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
                        log_type=log_type,
                        expectation=finalize_expectation_for_register(
                            expectation,
                            request.namespace,
                            supplier_code,
                            log_type,
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
    ) -> dict[str, dict]:
        mutated: dict[str, dict] = {}
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
                plugin.code,
                log_type,
            )
            mutated[log_type] = apply_supplier_mutation(
                mutated[log_type],
                plugin.code,
                log_type,
                request.hotel_id_for_supplier(plugin.code),
                request.supplier_mutations.get(plugin.code),
            )
        return mutated
