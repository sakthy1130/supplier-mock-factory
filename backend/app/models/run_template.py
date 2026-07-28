"""Request/Response models for run-template API."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class RunTemplateRequest(BaseModel):
    """Request to run a template and create a scenario.

    All fields are optional except template_id (passed in URL path).
    Defaults are optimized for CI/CD automation testing.
    """

    environment: str = Field(
        default="dev",
        description="Target environment: 'dev' or 'stg'",
        examples=["dev", "stg"]
    )
    check_in: Optional[str] = Field(
        default=None,
        description="Check-in date (YYYY-MM-DD). If not provided, uses today's date.",
        examples=["2026-07-29"]
    )
    check_out: Optional[str] = Field(
        default=None,
        description="Check-out date (YYYY-MM-DD). If not provided, uses tomorrow's date.",
        examples=["2026-07-30"]
    )
    hotel_id: Optional[str] = Field(
        default=None,
        description="Override the hotel ID from template. Uses template default if not provided.",
        examples=["123456"]
    )
    delete_mock_api_key: bool = Field(
        default=True,
        description="If true: full cleanup (delete scenario, mocks, contracts, API key). If false: keep scenario running for inspection."
    )
    assign_api_key_to_br: bool = Field(
        default=True,
        description="If true: assign generated API key to BR. If false: skip BR assignment."
    )
    force_cleanup: bool = Field(
        default=True,
        description="If true: cleanup even if scenario creation/run fails. If false: skip cleanup on error."
    )
    timeout_seconds: int = Field(
        default=300,
        description="Maximum seconds to wait for scenario creation and execution. Scenario creation: 10-30s, Scenario run: 10-60s.",
        ge=30,
        le=600
    )
    include_logs: bool = Field(
        default=False,
        description="If true: include full execution logs in response (larger response size). If false: omit logs (smaller response)."
    )


class StepStatus(BaseModel):
    """Status of a single execution step."""

    status: str  # SUCCESS, FAILED, SKIPPED
    duration_ms: int
    error: Optional[str] = None


class ExecutionSteps(BaseModel):
    """All execution steps and their status."""

    scenario_creation: StepStatus
    scenario_run: StepStatus
    cleanup: Optional[StepStatus] = None


class ExecutionSummary(BaseModel):
    """Overall execution summary."""

    total_duration_ms: int
    all_steps_successful: bool
    mocks_cleaned_up: bool
    steps_completed: int


class RunTemplateResponse(BaseModel):
    """Response from run-template API."""

    request_id: str
    status: str  # COMPLETED, FAILED, TIMEOUT
    scenario_id: Optional[str] = None
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    contract_id: Optional[str] = None
    search_id: Optional[str] = None
    package_id: Optional[str] = None

    check_in: Optional[str] = None
    check_out: Optional[str] = None
    hotel_id: Optional[str] = None

    deleted: bool = False
    assigned_to_br: bool = False

    steps: Optional[ExecutionSteps] = None
    summary: Optional[ExecutionSummary] = None

    error: Optional[dict] = None  # {code, message, step_failed, details}
    logs: Optional[list[str]] = None
