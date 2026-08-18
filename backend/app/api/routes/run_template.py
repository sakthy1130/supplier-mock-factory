"""API endpoint for running templates and creating scenarios."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_db
from app.db.repository import MongoStore
from app.db.models import ScenarioRecord
from app.env_context import get_current_env, use_env
from app.models.run_template import RunTemplateRequest, RunTemplateResponse
from app.services import scenario_service
from app.services import scenario_template_service
from app.models.scenario import ScenarioRequest, SupplierCode, SupplierScenario, PackageSpec
from app.utils.request_tracker import RequestTracker

router = APIRouter(prefix="/api/v1")


def build_scenario_request_from_template(
    template,
    request_data: "RunTemplateRequest",
    *,
    namespace: str,
    check_in: str,
    check_out: str,
    hotel_id: str,
    template_id: str,
) -> ScenarioRequest:
    """Assemble the ScenarioRequest an automation run creates from a template.

    Pure translation (no DB / network) so it is unit-testable:
    - Booking is opt-in: a package is marked for booking only when
      request_data.booking_package_index is set AND in range for that supplier's
      list; otherwise None (no Booking/GetOrder mocks, no booking flow).
    - SmartBooking uses the template's sb_enabled unless the request overrides it,
      and each supplier keeps its template assignment_target so contracts route to
      the apiKey / SB group / both. May raise pydantic ValidationError (e.g. SB on
      with no sbgroup/both supplier).
    """
    book_idx = request_data.booking_package_index
    sb_enabled = (
        request_data.sb_enabled if request_data.sb_enabled is not None else template.sb_enabled
    )

    suppliers: list[SupplierScenario] = []
    for supplier_entry in template.suppliers:
        packages_data = supplier_entry.packages
        if not packages_data:
            continue
        supplier_book_idx = (
            book_idx if (book_idx is not None and book_idx < len(packages_data)) else None
        )
        package_spec = PackageSpec(
            count=len(packages_data),
            room_basis=[pkg.room_basis for pkg in packages_data],
            room_names=[pkg.room_name for pkg in packages_data],
            prices=[pkg.price for pkg in packages_data],
            refundable=[pkg.refundable for pkg in packages_data],
            supplier_currency=supplier_entry.supplier_currency,
            booking_package_index=supplier_book_idx,
        )
        suppliers.append(
            SupplierScenario(
                code=SupplierCode(supplier_entry.supplier),
                contract_currency=supplier_entry.contract_currency,
                packages=package_spec,
                assignment_target=supplier_entry.assignment_target,
            )
        )

    return ScenarioRequest(
        namespace=namespace,
        check_in=check_in,
        check_out=check_out,
        atg_hotel_id=hotel_id,
        suppliers=suppliers,
        sb_enabled=sb_enabled,
        assign_to_br=request_data.assign_api_key_to_br,
        template_id=template_id,
    )


def _booking_selection_from_request(request: ScenarioRequest) -> Optional[dict]:
    """Derive the booking-flow package (price/board/room) from the first supplier
    that has a selected package, mirroring the UI Run path's _booking_selection.
    Returned to run_search_and_packages so core continues past packages into
    book -> poll -> getOrder; None leaves the run at search+packages only."""
    for supplier in request.suppliers:
        spec = supplier.packages
        if spec is None or spec.booking_package_index is None:
            continue
        idx = spec.booking_package_index
        room_basis = list(spec.room_basis) if isinstance(spec.room_basis, list) else [spec.room_basis]
        code = supplier.code.value if isinstance(supplier.code, SupplierCode) else supplier.code
        return {
            "supplier": code,
            "price": spec.prices[idx] if idx < len(spec.prices) else None,
            "board": room_basis[idx] if idx < len(room_basis) else None,
            "room_name": spec.room_names[idx] if idx < len(spec.room_names) else None,
        }
    return None


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
    tags=["Automation"],
)
async def run_template_endpoint(
    template_id: str = ...,
    request_data: Optional[RunTemplateRequest] = None,
    db: MongoStore = Depends(get_db),
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

        book_idx = request_data.booking_package_index
        sb_enabled = (
            request_data.sb_enabled if request_data.sb_enabled is not None else template.sb_enabled
        )
        tracker.log(
            f"Booking flow {'ENABLED at package index ' + str(book_idx) if book_idx is not None else 'DISABLED (no booking_package_index)'}"
        )
        tracker.log(
            f"SmartBooking {'ENABLED' if sb_enabled else 'DISABLED'} "
            f"(template={template.sb_enabled}, override={request_data.sb_enabled})"
        )

        # Build the scenario request from the template (may raise a validation
        # error, e.g. SB on with no SB-group supplier — surfaced as FAILED below).
        scenario_request = build_scenario_request_from_template(
            template,
            request_data,
            namespace=namespace,
            check_in=check_in,
            check_out=check_out,
            hotel_id=hotel_id,
            template_id=template_id,
        )

        # Resolve the target env FIRST — the mapping service is per-env (dev vs
        # staging hosts return different supplier hotel ids), so the resolution
        # below MUST run under the requested env or it silently bakes the wrong
        # env's hotel id into the mock (e.g. dev's 12323 for a stg scenario, which
        # the stg HMS can't map -> 0 search results).
        env = request_data.environment or get_current_env()

        # Resolve ATG hotel ID to supplier-specific hotel IDs via mapping API,
        # pinned to the requested env's mapping service.
        tracker.log(f"Resolving hotel mapping for ATG hotel: {hotel_id} (env={env})")
        from app.services.hotel_mapping_service import resolve_scenario_hotel_ids
        with use_env(env):
            scenario_request = await resolve_scenario_hotel_ids(scenario_request)
        tracker.log(f"Hotel mapping resolved: {scenario_request.supplier_hotel_ids}")
        # Surface the resolved ids so the caller can confirm the mock's hotel id
        # matches the core HMS mapping (a wrong id here = 0 search results).
        response.supplier_hotel_ids = dict(scenario_request.supplier_hotel_ids)

        # Create scenario
        tracker.log(f"Creating scenario: {namespace}")
        record = scenario_service.create_pending(db, scenario_request, env=env)
        scenario_id = record.id
        tracker.log(f"Scenario created: {scenario_id}")

        # Run scenario (async call)
        tracker.log(f"Running scenario: {scenario_id}")
        try:
            await scenario_service.run_create_scenario(scenario_id)
            tracker.log(f"Scenario async function completed")
        except Exception as e:
            tracker.log(f"Scenario run error: {e}")

        # Refresh database session to see updates from the standalone session
        db.expire_all()

        # Re-fetch the full record object with fresh data
        record = db.query(ScenarioRecord).filter(ScenarioRecord.id == scenario_id).first()

        if not record:
            tracker.log(f"Scenario record not found after creation")
            tracker.end_step("scenario_creation", success=False, error="Scenario not found")
            response.status = "FAILED"
            response.error = {
                "code": "SCENARIO_NOT_FOUND",
                "message": "Scenario was not found after creation",
            }
            return response

        tracker.log(f"Scenario status: {record.status}")

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
            # Critical: always cleanup mocks when creation fails (mocks were created but contracts/API keys failed)
            try:
                tracker.log("Creation failed - cleaning up orphaned mocks")
                await scenario_service.run_teardown(scenario_id)
                response.deleted = True
            except Exception as cleanup_err:
                tracker.log(f"Cleanup during creation failure: {cleanup_err}")
            return response

        tracker.log(f"Scenario ready: {record.status}")
        tracker.end_step("scenario_creation")

        # Populate response from record
        response.scenario_id = scenario_id
        response.api_key = record.api_key
        response.api_key_id = record.api_key_id
        response.check_in = check_in
        response.check_out = check_out
        response.hotel_id = hotel_id

        # Extract contract/SID/PID from record. contracts_json is
        # {instance_key: contract_id} — a template carrying the same supplier twice
        # produces two entries, so surface the whole map and keep contract_id as the
        # first value for callers that already read it.
        if record.contracts_json and isinstance(record.contracts_json, dict):
            response.contract_ids = dict(record.contracts_json)
            response.contract_id = next(iter(record.contracts_json.values()))

        # SmartBooking outcome: whether SB ran, the created group id, and the
        # apiKey/SB-group contract routing that was applied.
        response.sb_enabled = bool(sb_enabled)
        response.sb_group_id = getattr(record, "sb_group_id", None)
        if sb_enabled:
            response.contract_assignment = {
                "apikey": scenario_request.apikey_contract_codes(),
                "sbgroup": scenario_request.sbgroup_contract_codes(),
            }
            tracker.log(
                f"SB group={response.sb_group_id} apikey={response.contract_assignment['apikey']} "
                f"sbgroup={response.contract_assignment['sbgroup']}"
            )

        # suppliers_json contains search_id and package_id
        if record.suppliers_json and isinstance(record.suppliers_json, list) and len(record.suppliers_json) > 0:
            first_supplier = record.suppliers_json[0]
            if isinstance(first_supplier, dict):
                response.search_id = first_supplier.get("search_id")
                response.package_id = first_supplier.get("package_id")

        # Run scenario with core app. booking_selection is derived only when the
        # caller opted into the booking flow (booking_package_index set + valid);
        # passing it drives core through book -> poll -> getOrder, exactly like the
        # UI Run button. When None, the run stops at search + packages (no booking).
        booking_selection = _booking_selection_from_request(scenario_request)
        if book_idx is not None and booking_selection is None:
            response.booking_message = (
                f"booking_package_index={book_idx} is out of range for every "
                f"supplier in this template; booking skipped (search + packages only)."
            )
            tracker.log(response.booking_message)
        tracker.log(f"Booking selection for run: {booking_selection}")
        tracker.start_step("scenario_run")
        try:
            from app.integrations.core_app import CoreAppClient

            with use_env(record.env):
                async with CoreAppClient() as client:
                    result = await client.run_search_and_packages(
                        api_key=record.api_key,
                        check_in=record.check_in,
                        check_out=record.check_out,
                        hotel_id=record.hotel_id,
                        booking_selection=booking_selection,
                    )
            tracker.log(f"Scenario run completed: {result}")

            # Capture search_id and package_id from result
            if result.search_s_id:
                response.search_id = result.search_s_id
            if result.package_p_id:
                response.package_id = result.package_p_id
            response.search_status = result.search_status
            response.package_status = result.package_status

            # Judge whether the run actually succeeded — a search that returns 0
            # usable results still comes back without an exception, so COMPLETED
            # must NOT be reported blindly. Packages producing a pId is the floor;
            # a booking run must also yield a bId.
            if result.error_message:
                run_error = {"code": "CORE_RUN_FAILED", "message": result.error_message}
            elif not result.package_p_id:
                run_error = {
                    "code": "NO_PACKAGES",
                    "message": (
                        f"Search completed (status={result.search_status}) but produced no "
                        f"packages (no pId). Most common cause: the supplier hotel id baked "
                        f"into the mock is not mapped in the core's HMS for ATG hotel "
                        f"{record.hotel_id}, so the returned hotel is dropped before packages. "
                        f"Verify the ATG hotel has a valid supplier mapping "
                        f"(search_hotel_id={result.search_hotel_id})."
                    ),
                }
            elif booking_selection is not None and not result.booking_b_id:
                run_error = {
                    "code": "BOOKING_FAILED",
                    "message": result.booking_message or "Booking did not produce a bId.",
                }
            elif booking_selection is not None and result.booking_match is not True:
                # A bId can come back even when the booking ultimately fails
                # (e.g. COMPLETED_WITH_FAILURE / totalResults 0 / order mismatch);
                # only a matched order counts as success.
                run_error = {
                    "code": "BOOKING_FAILED",
                    "message": result.booking_message
                    or f"Booking did not succeed (status={result.booking_status}, match={result.booking_match}).",
                }
            else:
                run_error = None

            # Surface the booking-flow outcome only when booking actually ran, so
            # a search+packages-only run doesn't report misleading null booking
            # fields (and an out-of-range warning set above is preserved).
            if booking_selection is not None:
                response.booking_id = result.booking_b_id
                response.booking_status = result.booking_status
                response.order_status = result.order_status
                response.booking_match = result.booking_match
                response.booking_message = result.booking_message
                tracker.log(
                    f"Booking outcome: bId={result.booking_b_id} "
                    f"status={result.booking_status} order={result.order_status} "
                    f"match={result.booking_match}"
                )

            tracker.end_step("scenario_run")
        except Exception as e:
            tracker.end_step("scenario_run", success=False, error=str(e))
            if request_data.force_cleanup:
                tracker.log("Cleanup enabled on error, tearing down scenario")
                try:
                    await scenario_service.run_teardown(scenario_id)
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
                await scenario_service.run_teardown(scenario_id)
                response.deleted = True
                tracker.log("Scenario cleaned up")
                tracker.end_step("cleanup")
            except Exception as e:
                tracker.log(f"Cleanup warning: {e}")
                tracker.end_step("cleanup", success=False, error=str(e))
        else:
            tracker.log("Cleanup skipped (delete_mock_api_key=false)")

        # Report the real outcome: COMPLETED only when the core run actually
        # produced packages (and a booking, if one was requested).
        response.assigned_to_br = request_data.assign_api_key_to_br
        if run_error is not None:
            response.status = "FAILED"
            response.error = run_error
            tracker.log(f"Run-template FAILED: {run_error['code']} - {run_error['message']}")
        else:
            response.status = "COMPLETED"
            tracker.log("Run-template completed successfully")
        response.logs = tracker.get_logs() if request_data.include_logs else None
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
