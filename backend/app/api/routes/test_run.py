"""Live test-run API — started by Java TestExecutionListener, polled by React UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models.test_run import TestResult, TestRunStartResponse, TestRunState
from app.services import test_run_store, provisioning_log_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test-run", tags=["test-run"])


@router.post("/start", response_model=TestRunStartResponse, status_code=201)
def start_test_run() -> TestRunStartResponse:
    """Called once before mvn test starts. Returns run_id for all subsequent calls."""
    response = test_run_store.start_run()
    logger.info("Test run started via API: run_id=%s", response.run_id)
    return response


@router.post("/{run_id}/result", status_code=204)
def post_test_result(run_id: str, result: TestResult) -> None:
    """Called by JUnit TestExecutionListener after each test completes.

    Returns 204 No Content on success. If run_id is unknown, an orphan run is
    created (so a lost run_id doesn't break the full test suite).
    """
    # Attach provisioning log from cache so the dashboard can show it per test result
    if result.scenario_id:
        plog = provisioning_log_cache.get(result.scenario_id)
        if plog:
            result.provisioning_log = plog
            logger.info(
                "Attached provisioning_log (%d entries) to result: scenario_id=%s run_id=%s",
                len(plog), result.scenario_id, run_id,
            )
    test_run_store.post_result(run_id, result)


@router.post("/{run_id}/complete", status_code=204)
def complete_test_run(run_id: str) -> None:
    """Called when Maven subprocess exits. Marks the run as COMPLETE."""
    state = test_run_store.get_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    test_run_store.complete_run(run_id)


@router.get("/{run_id}/status", response_model=TestRunState)
def get_run_status(run_id: str) -> TestRunState:
    """Polled by React UI every 2s. Returns full run state including all results."""
    state = test_run_store.get_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return state


@router.get("", response_model=list[TestRunState])
def list_test_runs() -> list[TestRunState]:
    """List all runs in memory — most recent first."""
    return test_run_store.list_runs()
