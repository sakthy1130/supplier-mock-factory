"""Service for running templates and creating scenarios."""

from __future__ import annotations

import uuid
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.run_template import (
    RunTemplateRequest,
    RunTemplateResponse,
    StepStatus,
    ExecutionSteps,
    ExecutionSummary,
)
from app.utils.request_tracker import RequestTracker
from app.services.scenario_template_service import list_templates
from app.services.scenario_service import (
    create_scenario,
    run_scenario_service,
    teardown_scenario,
)
from app.models.scenario import ScenarioRequest, SupplierCode


def get_template_by_id(db: Session, template_id: str):
    """Get template by ID from all templates."""
    templates = list_templates(db)
    for t in templates:
        if t.id == template_id:
            return t
    return None


def run_template(
    db: Session,
    template_id: str,
    request: RunTemplateRequest,
) -> tuple[RunTemplateResponse, int]:
    """
    Run a template: create scenario, run it, optionally cleanup.

    Returns: (response, status_code)
    """
    tracker = RequestTracker()
    response = RunTemplateResponse(request_id=tracker.request_id)

    try:
        # Load template
        tracker.start_step("template_load")
        template = get_template_by_id(db, template_id)
        if not template:
            tracker.end_step("template_load", success=False, error="Template not found")
            response.status = "FAILED"
            response.error = {
                "code": "TEMPLATE_NOT_FOUND",
                "message": f"Template {template_id} not found",
            }
            return response, 404
        tracker.end_step("template_load")
        tracker.log(f"Loaded template: {template.label}")

        # Determine dates
        check_in = request.check_in or datetime.now().strftime("%Y-%m-%d")
        check_out = request.check_out or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        tracker.log(f"Using dates: {check_in} to {check_out}")

        # Generate namespace
        namespace = f"{template_id}-{str(uuid.uuid4())[:8]}"
        tracker.log(f"Generated namespace: {namespace}")

        # Build scenario request from template
        tracker.start_step("scenario_creation")
        scenario_request = _build_scenario_request(
            template=template,
            namespace=namespace,
            environment=request.environment,
            check_in=check_in,
            check_out=check_out,
            hotel_id=request.hotel_id,
            assign_to_br=request.assign_api_key_to_br,
        )
        tracker.log(f"Built scenario request for: {namespace}")

        # Create scenario
        scenario_bundle = create_scenario(db, scenario_request)
        scenario_id = scenario_bundle.id
        tracker.log(f"Scenario created: {scenario_id}")
        tracker.end_step("scenario_creation")

        response.scenario_id = scenario_id
        response.api_key = scenario_bundle.api_key
        response.api_key_id = scenario_bundle.api_key_id
        response.check_in = check_in
        response.check_out = check_out
        response.hotel_id = scenario_request.atg_hotel_id

        # Extract contract/SID/PID from scenario
        if scenario_bundle.contracts_json and len(scenario_bundle.contracts_json) > 0:
            response.contract_id = scenario_bundle.contracts_json[0].get("id")
        if scenario_bundle.suppliers_json and len(scenario_bundle.suppliers_json) > 0:
            first_supplier = scenario_bundle.suppliers_json[0]
            if "search_id" in first_supplier:
                response.search_id = first_supplier.get("search_id")
            if "package_id" in first_supplier:
                response.package_id = first_supplier.get("package_id")

        # Run scenario
        tracker.start_step("scenario_run")
        try:
            run_result = run_scenario_service(db, scenario_id)
            tracker.log(f"Scenario run completed: {run_result.get('status')}")
            tracker.end_step("scenario_run")
        except Exception as e:
            tracker.end_step("scenario_run", success=False, error=str(e))
            if request.force_cleanup:
                tracker.log("Cleanup enabled on error, tearing down scenario")
                try:
                    teardown_scenario(db, scenario_id, request.environment)
                    response.deleted = True
                    tracker.end_step("cleanup")
                except Exception as cleanup_err:
                    tracker.log(f"Cleanup failed: {cleanup_err}", level="ERROR")
                    tracker.end_step("cleanup", success=False, error=str(cleanup_err))

            response.status = "FAILED"
            response.error = {
                "code": "SCENARIO_RUN_FAILED",
                "message": str(e),
                "step_failed": "scenario_run",
            }
            response.steps = _build_execution_steps(tracker)
            response.summary = _build_execution_summary(tracker, response.deleted)
            response.logs = tracker.get_logs() if request.include_logs else None
            return response, 500

        # Cleanup if requested
        if request.delete_mock_api_key:
            tracker.start_step("cleanup")
            try:
                teardown_scenario(db, scenario_id, request.environment)
                response.deleted = True
                tracker.log("Scenario and mocks cleaned up")
                tracker.end_step("cleanup")
            except Exception as e:
                tracker.log(f"Cleanup error: {e}", level="WARNING")
                tracker.end_step("cleanup", success=False, error=str(e))
        else:
            tracker.log("Cleanup skipped (delete_mock_api_key=false)")

        # Success response
        response.status = "COMPLETED"
        response.assigned_to_br = request.assign_api_key_to_br
        response.steps = _build_execution_steps(tracker)
        response.summary = _build_execution_summary(tracker, response.deleted)
        response.logs = tracker.get_logs() if request.include_logs else None

        tracker.log("Run-template completed successfully")
        return response, 200

    except Exception as e:
        tracker.log(f"Unexpected error: {e}", level="ERROR")
        response.status = "FAILED"
        response.error = {
            "code": "INTERNAL_ERROR",
            "message": str(e),
        }
        response.steps = _build_execution_steps(tracker)
        response.summary = _build_execution_summary(tracker, False)
        response.logs = tracker.get_logs() if request.include_logs else None
        return response, 500


def _build_scenario_request(
    template,
    namespace: str,
    environment: str,
    check_in: str,
    check_out: str,
    hotel_id: Optional[str],
    assign_to_br: bool,
) -> ScenarioRequest:
    """Build ScenarioRequest from template and overrides."""
    # Use overridden hotel_id or template's
    final_hotel_id = hotel_id or template.atg_hotel_id

    # Build suppliers list from template
    suppliers = []
    for supplier_entry in template.suppliers:
        supplier_code = supplier_entry.get("supplier")
        supplier_currency = supplier_entry.get("supplier_currency", "SAR")
        contract_currency = supplier_entry.get("contract_currency", "USD")

        # Convert packages dict to PackageSpec objects
        from app.models.scenario import PackageSpec

        packages_data = supplier_entry.get("packages", [])
        if packages_data:
            package_spec = PackageSpec(
                count=packages_data[0].get("count", 1) if packages_data else 1,
                room_basis=packages_data[0].get("room_basis", ["RO"]) if packages_data else ["RO"],
                room_names=packages_data[0].get("room_names", ["Room"]) if packages_data else ["Room"],
                prices=packages_data[0].get("prices", [100.0]) if packages_data else [100.0],
                refundable=packages_data[0].get("refundable", [True]) if packages_data else [True],
                supplier_currency=supplier_currency,
            )

            from app.models.scenario import SupplierScenario

            suppliers.append(
                SupplierScenario(
                    code=SupplierCode(supplier_code),
                    contract_currency=contract_currency,
                    packages=package_spec,
                )
            )

    return ScenarioRequest(
        namespace=namespace,
        check_in=check_in,
        check_out=check_out,
        atg_hotel_id=final_hotel_id,
        suppliers=suppliers,
        assign_to_br=assign_to_br,
    )


def _build_execution_steps(tracker: RequestTracker) -> ExecutionSteps:
    """Build ExecutionSteps from tracker data."""
    steps_data = tracker.step_times

    scenario_creation = steps_data.get("scenario_creation", {})
    scenario_run = steps_data.get("scenario_run", {})
    cleanup = steps_data.get("cleanup")

    return ExecutionSteps(
        scenario_creation=StepStatus(
            status=scenario_creation.get("status", "UNKNOWN"),
            duration_ms=scenario_creation.get("duration_ms", 0),
            error=scenario_creation.get("error"),
        ),
        scenario_run=StepStatus(
            status=scenario_run.get("status", "UNKNOWN"),
            duration_ms=scenario_run.get("duration_ms", 0),
            error=scenario_run.get("error"),
        ),
        cleanup=StepStatus(
            status=cleanup.get("status", "UNKNOWN"),
            duration_ms=cleanup.get("duration_ms", 0),
            error=cleanup.get("error"),
        ) if cleanup else None,
    )


def _build_execution_summary(tracker: RequestTracker, cleaned_up: bool) -> ExecutionSummary:
    """Build ExecutionSummary from tracker data."""
    total_ms = tracker.get_total_duration_ms()
    steps = tracker.step_times
    successful = all(s.get("status") == "SUCCESS" for s in steps.values())

    return ExecutionSummary(
        total_duration_ms=total_ms,
        all_steps_successful=successful,
        mocks_cleaned_up=cleaned_up,
        steps_completed=len(steps),
    )
