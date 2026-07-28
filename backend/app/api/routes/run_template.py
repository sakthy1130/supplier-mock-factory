"""API endpoint for running templates and creating scenarios."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.env_context import get_current_env, use_env
from app.models.run_template import RunTemplateRequest, RunTemplateResponse
from app.services import scenario_service
from app.services import scenario_template_service
from app.models.scenario import ScenarioRequest, SupplierCode, SupplierScenario, PackageSpec
from app.utils.request_tracker import RequestTracker

router = APIRouter(prefix="/api/v1", tags=["run-template"])


@router.post(
    "/run-template/{template_id}",
    response_model=RunTemplateResponse,
    summary="Create and run a scenario from template",
    description="""
    Automated scenario creation and execution from a saved template.

    **Workflow:**
    1. Load template by ID
    2. Create scenario from template
    3. Run scenario against core app
    4. Optionally cleanup (delete mocks, contracts, API key)

    **Returns:**
    - Complete scenario details (ID, API key, contracts, SID, PID)
    - Step-by-step execution tracking with timing
    - Execution summary and metrics
    - Optional logs for debugging
    - Request ID for system-wide tracing

    **Use Cases:**
    - Automation testing: create test data, run test, cleanup
    - CI/CD pipelines: provision mocks in build step
    - Performance testing: generate multiple scenarios
    - QA validation: verify scenario creation and execution
    """,
    responses={
        200: {
            "description": "Scenario created and executed successfully",
            "model": RunTemplateResponse,
        },
        404: {
            "description": "Template not found",
            "model": RunTemplateResponse,
        },
        408: {
            "description": "Scenario creation/execution timed out",
            "model": RunTemplateResponse,
        },
        500: {
            "description": "Internal server error",
            "model": RunTemplateResponse,
        },
    },
    tags=["Automation", "Templates"],
)
async def run_template_endpoint(
    template_id: str = ...,
    request_data: Optional[RunTemplateRequest] = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
) -> RunTemplateResponse:
    """Execute a template as a complete scenario workflow."""
    # Default request if not provided
    if not request_data:
        request_data = RunTemplateRequest(environment="dev")

    tracker = RequestTracker()
    response = RunTemplateResponse(
        request_id=tracker.request_id,
        status="PENDING"  # Initialize with default status
    )

    try:
        # Load template
        tracker.start_step("scenario_creation")
        templates = scenario_template_service.list_templates(db)
        template = None
        for t in templates:
            if t.id == template_id:
                template = t
                break

        if not template:
            tracker.end_step("scenario_creation", success=False, error="Template not found")
            response.status = "FAILED"
            response.error = {
                "code": "TEMPLATE_NOT_FOUND",
                "message": f"Template {template_id} not found",
            }
            return response

        tracker.log(f"Loaded template: {template.label}")

        # Determine dates
        check_in = request_data.check_in or datetime.now().strftime("%Y-%m-%d")
        check_out = request_data.check_out or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        tracker.log(f"Using dates: {check_in} to {check_out}")

        # Determine hotel_id
        hotel_id = request_data.hotel_id or template.atg_hotel_id
        tracker.log(f"Using hotel_id: {hotel_id}")

        # Generate namespace (unique per run)
        namespace = f"{template_id}-{str(uuid.uuid4())[:8]}"
        tracker.log(f"Generated namespace: {namespace}")

        # Build scenario request from template
        suppliers = []
        for supplier_entry in template.suppliers:
            supplier_code = supplier_entry.get("supplier")
            supplier_currency = supplier_entry.get("supplier_currency", "SAR")
            contract_currency = supplier_entry.get("contract_currency", "USD")

            packages_data = supplier_entry.get("packages", [])
            if packages_data:
                first_pkg = packages_data[0]
                package_spec = PackageSpec(
                    count=first_pkg.get("count", 1),
                    room_basis=first_pkg.get("room_basis", ["RO"]),
                    room_names=first_pkg.get("room_names", ["Room"]),
                    prices=first_pkg.get("prices", [100.0]),
                    refundable=first_pkg.get("refundable", [True]),
                    supplier_currency=supplier_currency,
                )
                suppliers.append(
                    SupplierScenario(
                        code=SupplierCode(supplier_code),
                        contract_currency=contract_currency,
                        packages=package_spec,
                    )
                )

        scenario_request = ScenarioRequest(
            namespace=namespace,
            check_in=check_in,
            check_out=check_out,
            atg_hotel_id=hotel_id,
            suppliers=suppliers,
            assign_to_br=request_data.assign_api_key_to_br,
        )

        # Create scenario
        tracker.log(f"Creating scenario: {namespace}")
        env = request_data.environment or get_current_env()
        record = scenario_service.create_pending(db, scenario_request, env=env)
        scenario_id = record.id
        tracker.log(f"Scenario created: {scenario_id}")

        # Run scenario in background but wait for it
        tracker.log(f"Running scenario: {scenario_id}")
        background_tasks.add_task(scenario_service.run_create_scenario, scenario_id)

        # Wait for scenario to be ready (with timeout)
        import time

        start = time.time()
        while (time.time() - start) < request_data.timeout_seconds:
            record = scenario_service.get_record(db, scenario_id)
            if record.status != "PENDING":
                break
            time.sleep(0.5)

        if record.status == "PENDING":
            tracker.end_step("scenario_creation", success=False, error="Scenario creation timed out")
            response.status = "TIMEOUT"
            response.error = {
                "code": "SCENARIO_CREATION_TIMEOUT",
                "message": f"Scenario creation exceeded {request_data.timeout_seconds}s",
            }
            return response

        if record.status == "FAILED":
            tracker.end_step("scenario_creation", success=False, error=record.error_message)
            response.status = "FAILED"
            response.error = {
                "code": "SCENARIO_CREATION_FAILED",
                "message": record.error_message or "Unknown error",
            }
            return response

        tracker.log(f"Scenario ready: {record.status}")
        tracker.end_step("scenario_creation")

        bundle = scenario_service.record_to_bundle(record)
        response.scenario_id = scenario_id
        response.api_key = bundle.api_key
        response.api_key_id = bundle.api_key_id
        response.check_in = check_in
        response.check_out = check_out
        response.hotel_id = hotel_id

        # Extract contract/SID/PID
        if bundle.contracts_json and len(bundle.contracts_json) > 0:
            response.contract_id = bundle.contracts_json[0].get("id")
        if bundle.suppliers_json and len(bundle.suppliers_json) > 0:
            first_supplier = bundle.suppliers_json[0]
            response.search_id = first_supplier.get("search_id")
            response.package_id = first_supplier.get("package_id")

        # Run scenario with core app
        tracker.start_step("scenario_run")
        try:
            from app.services.crawla_service import CoreAppClient

            with use_env(record.env):
                async with CoreAppClient() as client:
                    result = await client.run_search_and_packages(
                        api_key=bundle.api_key,
                        check_in=bundle.check_in,
                        check_out=bundle.check_out,
                        hotel_id=bundle.atg_hotel_id,
                    )
            tracker.log(f"Scenario run completed: {result}")
            tracker.end_step("scenario_run")
        except Exception as e:
            tracker.end_step("scenario_run", success=False, error=str(e))
            if request_data.force_cleanup:
                tracker.log("Cleanup enabled on error, tearing down scenario")
                try:
                    scenario_service.queue_teardown_all(db, env=env)
                    response.deleted = True
                except Exception as cleanup_err:
                    tracker.log(f"Cleanup failed: {cleanup_err}")

            response.status = "FAILED"
            response.error = {
                "code": "SCENARIO_RUN_FAILED",
                "message": str(e),
            }
            response.logs = tracker.get_logs() if request_data.include_logs else None
            return response

        # Cleanup if requested
        if request_data.delete_mock_api_key:
            tracker.start_step("cleanup")
            try:
                scenario_service.queue_teardown_all(db, env=env)
                response.deleted = True
                tracker.log("Scenario cleaned up")
                tracker.end_step("cleanup")
            except Exception as e:
                tracker.log(f"Cleanup warning: {e}")
                tracker.end_step("cleanup", success=False, error=str(e))
        else:
            tracker.log("Cleanup skipped (delete_mock_api_key=false)")

        # Success
        response.status = "COMPLETED"
        response.assigned_to_br = request_data.assign_api_key_to_br
        response.logs = tracker.get_logs() if request_data.include_logs else None

        tracker.log("Run-template completed successfully")
        return response

    except Exception as e:
        tracker.log(f"Unexpected error: {str(e)}")
        response.status = "FAILED"
        response.error = {
            "code": "INTERNAL_ERROR",
            "message": str(e),
        }
        response.logs = tracker.get_logs() if request_data.include_logs else None
        return response
