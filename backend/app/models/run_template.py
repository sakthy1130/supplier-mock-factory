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
    booking_package_index: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Opt into the booking flow. When set, the run drives core through "
            "book -> poll -> getOrder for the package at this 0-based index (and "
            "the Booking/GetOrder mocks are created for it). Omit (null) to run "
            "search + packages only, exactly like the UI when no package is picked "
            "to book. The index is per supplier's package list; the first supplier "
            "whose list contains it is booked."
        ),
        examples=[0],
    )
    sb_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Override the template's SmartBooking setting. null (default) uses the "
            "template's saved sb_enabled; true/false forces it on/off for this run. "
            "When on, an SB group is created and each supplier's contract is routed "
            "per its template assignment_target (apikey / sbgroup / both). At least "
            "one supplier must target sbgroup/both, or the run fails validation."
        ),
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
    # Core poll statuses so a caller can see how far the run got.
    search_status: Optional[str] = None
    package_status: Optional[str] = None

    check_in: Optional[str] = None
    check_out: Optional[str] = None
    hotel_id: Optional[str] = None
    # The per-supplier hotel ids resolved from the mapping service and baked into
    # the mocks. Surfaced so a caller can confirm the mock's hotel id matches the
    # core HMS mapping (a stale/wrong id here == 0 search results downstream).
    supplier_hotel_ids: Optional[dict] = None

    # Booking-flow outcome (populated when the template selected a package for
    # booking, i.e. the run drove core through book -> poll -> getOrder).
    booking_id: Optional[str] = None
    booking_status: Optional[str] = None
    order_status: Optional[str] = None
    booking_match: Optional[bool] = None
    booking_message: Optional[str] = None

    # SmartBooking outcome: whether SB was on for this run, the created SB group
    # id (if any), and where each supplier's contract was attached.
    sb_enabled: bool = False
    sb_group_id: Optional[str] = None
    contract_assignment: Optional[dict] = None  # {"apikey": [...codes], "sbgroup": [...codes]}

    deleted: bool = False
    assigned_to_br: bool = False

    steps: Optional[ExecutionSteps] = None
    summary: Optional[ExecutionSummary] = None

    error: Optional[dict] = None  # {code, message, step_failed, details}
    logs: Optional[list[str]] = None
