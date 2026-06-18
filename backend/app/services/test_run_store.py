"""In-memory store for live test run state.

Each test run is identified by a run_id (UUID). The JUnit TestExecutionListener
posts one TestResult per completed test. The React UI polls GET /api/test-run/{run_id}/status.

Thread-safety: FastAPI runs async so access is single-threaded in one event loop.
No external dependencies required — pure in-memory dict.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.models.test_run import RunStatus, StepNode, TestResult, TestRunStartResponse, TestRunState, TestStatus

logger = logging.getLogger(__name__)

# Global in-memory store: run_id -> TestRunState
_store: dict[str, TestRunState] = {}

# Steps that arrived before their result was posted: (run_id, test_method) -> steps
_pending_steps: dict[tuple[str, str], list[StepNode]] = {}


def start_run() -> TestRunStartResponse:
    """Create a new test run session and return its run_id."""
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    state = TestRunState(
        run_id=run_id,
        status=RunStatus.RUNNING,
        started_at=started_at,
    )
    _store[run_id] = state
    logger.info("Test run started: run_id=%s", run_id)
    return TestRunStartResponse(run_id=run_id, started_at=started_at)


def post_result(run_id: str, result: TestResult) -> None:
    """Append one test result to the run state."""
    state = _store.get(run_id)
    if state is None:
        logger.warning("post_result: unknown run_id=%s — creating orphan run", run_id)
        state = TestRunState(
            run_id=run_id,
            status=RunStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        _store[run_id] = state

    result.posted_at = datetime.now(timezone.utc)
    # Steps may have arrived before this result — merge them in.
    pending = _pending_steps.pop((run_id, result.test_method), None)
    if pending and not result.steps:
        result.steps = pending
    state.results.append(result)
    state.total += 1

    if result.status == TestStatus.PASSED:
        state.passed += 1
    elif result.status == TestStatus.FAILED:
        state.failed += 1
    elif result.status in (TestStatus.SKIPPED, TestStatus.ABORTED):
        # Assumption-failures (e.g. Crawla service absent) arrive as ABORTED;
        # count them as skipped so they show in the dashboard breakdown,
        # matching how Surefire reports them.
        state.skipped += 1

    logger.debug(
        "Test result posted: run_id=%s scenario=%s status=%s duration_ms=%d",
        run_id,
        result.scenario_id,
        result.status,
        result.duration_ms,
    )


def attach_steps(run_id: str, test_method: str, steps: list[StepNode]) -> None:
    """Attach an Allure @Step tree to the matching result, or buffer it until the
    result is posted. Keyed by test_method within the run."""
    state = _store.get(run_id)
    if state is not None:
        # Most recent matching result without steps yet.
        for result in reversed(state.results):
            if result.test_method == test_method and not result.steps:
                result.steps = steps
                logger.info("Attached %d step(s) to result: run_id=%s test=%s", len(steps), run_id, test_method)
                return
    _pending_steps[(run_id, test_method)] = steps
    logger.debug("Buffered steps for not-yet-posted result: run_id=%s test=%s", run_id, test_method)


def complete_run(run_id: str) -> None:
    """Mark a run as complete. Called when Maven subprocess exits."""
    state = _store.get(run_id)
    if state is None:
        logger.warning("complete_run: unknown run_id=%s", run_id)
        return
    state.status = RunStatus.COMPLETE
    state.completed_at = datetime.now(timezone.utc)
    logger.info(
        "Test run complete: run_id=%s passed=%d failed=%d skipped=%d total=%d",
        run_id,
        state.passed,
        state.failed,
        state.skipped,
        state.total,
    )


def get_state(run_id: str) -> TestRunState | None:
    """Return current state for polling."""
    return _store.get(run_id)


def list_runs() -> list[TestRunState]:
    """Return all runs — most recent first."""
    return sorted(_store.values(), key=lambda s: s.started_at or datetime.min, reverse=True)
