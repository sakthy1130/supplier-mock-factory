"""Scenario REST API — P5 SQLite + background jobs."""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
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
    resolved = await resolve_scenario_hotel_ids(request)
    record = scenario_service.create_pending(db, resolved)
    background_tasks.add_task(scenario_service.run_create_scenario, record.id)
    return scenario_service.record_to_bundle(record)


@router.get("", response_model=list[ScenarioListItem])
def list_scenarios(db: Session = Depends(get_db)) -> list[ScenarioListItem]:
    return [scenario_service.record_to_list_item(r) for r in scenario_service.list_records(db)]


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
    )


@router.get("/{scenario_id}", response_model=ScenarioBundle)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)) -> ScenarioBundle:
    return scenario_service.record_to_bundle(scenario_service.get_record(db, scenario_id))


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
    result = scenario_service.queue_teardown_all(db)
    if result.queued:
        background_tasks.add_task(scenario_service.run_teardown_all)
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
