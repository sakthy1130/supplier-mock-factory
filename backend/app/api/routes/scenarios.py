"""Scenario REST API — P5 SQLite + background jobs."""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.env_context import get_current_env, use_env
from app.integrations.core_app import CoreAppClient
from app.models.crawla import CrawlaRunScenarioResponse
from app.models.quickwit import QuickwitSearchResponse
from app.services.quickwit_service import run_quickwit_search_http
from app.models.scenario import (
    ScenarioBundle,
    ScenarioListItem,
    ScenarioRequest,
    ScenarioStatus,
    TeardownAllResponse,
)
from app.services import scenario_service
from app.services.hotel_mapping_service import resolve_scenario_hotel_ids

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("", response_model=ScenarioBundle, status_code=202)
async def create_scenario(
    request: ScenarioRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScenarioBundle:
    env = get_current_env()
    resolved = await resolve_scenario_hotel_ids(request)
    record = scenario_service.create_pending(db, resolved, env=env)
    background_tasks.add_task(scenario_service.run_create_scenario, record.id)
    return scenario_service.record_to_bundle(record)


@router.get("", response_model=list[ScenarioListItem])
def list_scenarios(
    db: Session = Depends(get_db),
    env: Optional[str] = Query(default=None, description="'dev', 'stg', or 'all' for no filter"),
) -> list[ScenarioListItem]:
    resolved_env = None if env == "all" else (env or get_current_env())
    return [
        scenario_service.record_to_list_item(r)
        for r in scenario_service.list_records(db, env=resolved_env)
    ]


@router.get("/{scenario_id}/quickwit-logs", response_model=QuickwitSearchResponse)
async def scenario_quickwit_logs(
    scenario_id: str,
    minutes: int = Query(default=60, ge=1, le=24 * 60),
    query: Optional[str] = Query(default=None, description="Override; default api_key or namespace"),
    max_hits: int = Query(default=3_000, ge=1, le=10_000),
    db: Session = Depends(get_db),
) -> QuickwitSearchResponse:
    """Search Quickwit console logs for this scenario's api_key / namespace."""
    record = scenario_service.get_record(db, scenario_id)
    if record.status == ScenarioStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="Scenario still provisioning")

    search_query = query or record.api_key or record.namespace
    if not search_query:
        raise HTTPException(status_code=409, detail="Scenario has no api_key or namespace to search")

    return await run_quickwit_search_http(
        search_query,
        index=None,
        minutes=minutes,
        max_hits=max_hits,
        env=record.env,
    )


@router.get("/{scenario_id}", response_model=ScenarioBundle)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)) -> ScenarioBundle:
    return scenario_service.record_to_bundle(scenario_service.get_record(db, scenario_id))


@router.post("/{scenario_id}/run", response_model=CrawlaRunScenarioResponse)
async def run_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
) -> CrawlaRunScenarioResponse:
    """Fire a real search + packages against the core app with this scenario's apiKey.

    Same core flow as the Crawla run, but available to any READY scenario (no Crawla
    export required). Returns the search sId + statuses for staging trace/validation.
    """
    record = scenario_service.get_record(db, scenario_id)
    bundle = scenario_service.record_to_bundle(record)
    if bundle.status != ScenarioStatus.READY:
        raise HTTPException(status_code=409, detail="Scenario must be READY before running")
    if not bundle.api_key:
        raise HTTPException(status_code=409, detail="Scenario has no apiKey")

    # When the scenario picked a package for the booking flow, drive core all the
    # way through book → getOrder and verify the retrieved order matches it.
    booking_selection = _booking_selection(bundle.request)

    # Pin to the scenario's own env — its apiKey/contracts only exist there,
    # regardless of what env is currently selected in the UI.
    with use_env(record.env):
        async with CoreAppClient() as client:
            result = await client.run_search_and_packages(
                api_key=bundle.api_key,
                check_in=bundle.check_in,
                check_out=bundle.check_out,
                hotel_id=bundle.atg_hotel_id,
                booking_selection=booking_selection,
            )

    result.scenario_id = scenario_id
    if booking_selection is None:
        result.booking_message = (
            "No package was selected for the booking flow when this scenario was "
            "created, so only search + packages ran (no Booking/GetOrder mocks exist). "
            "Re-create the scenario and pick a 'Book' package to exercise the booking flow."
        )
    return result


def _booking_selection(request: Optional[dict]) -> Optional[dict]:
    """Derive the booking-flow package (price/board/room) to verify against, from
    the first supplier in the stored request that has a selected package."""
    if not isinstance(request, dict):
        return None
    for supplier in request.get("suppliers", []) or []:
        if not isinstance(supplier, dict):
            continue
        packages = supplier.get("packages")
        if not isinstance(packages, dict):
            continue
        idx = packages.get("booking_package_index")
        if idx is None:
            continue
        prices = packages.get("prices") or []
        room_basis = packages.get("room_basis") or []
        room_names = packages.get("room_names") or []
        return {
            "supplier": supplier.get("code"),
            "price": prices[idx] if idx < len(prices) else None,
            "board": room_basis[idx] if idx < len(room_basis) else None,
            "room_name": room_names[idx] if idx < len(room_names) else None,
        }
    return None


@router.post("/{scenario_id}/refresh-booking-ids", response_model=ScenarioBundle, status_code=202)
def refresh_booking_ids(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScenarioBundle:
    record = scenario_service.get_record(db, scenario_id)
    if record.status != ScenarioStatus.READY.value:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Scenario must be READY to refresh booking ids")
    background_tasks.add_task(scenario_service.run_refresh_booking_ids, scenario_id)
    return scenario_service.record_to_bundle(record)


@router.delete("/all", response_model=TeardownAllResponse, status_code=202)
def teardown_all_scenarios(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TeardownAllResponse:
    # Scoped to the currently selected env — clearing dev's mess must not touch
    # stg's mocks/contracts (and vice versa); they live on different MockServer
    # hosts entirely.
    env = get_current_env()
    result = scenario_service.queue_teardown_all(db, env=env)
    if result.queued:
        background_tasks.add_task(scenario_service.run_teardown_all, env)
    return result


@router.delete("/{scenario_id}", response_model=ScenarioBundle, status_code=202)
def teardown_scenario(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScenarioBundle:
    record = scenario_service.get_record(db, scenario_id)
    if record.status == ScenarioStatus.TORN_DOWN.value:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Scenario already torn down")
    background_tasks.add_task(scenario_service.run_teardown, scenario_id)
    return scenario_service.record_to_bundle(record)
