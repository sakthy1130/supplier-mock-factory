"""Request/Response models for run-template API."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class RunTemplateRequest(BaseModel):
    """Request to run a template and create a scenario."""

    environment: str = Field(default="dev", description="dev or stg")
    check_in: Optional[str] = Field(default=None, description="YYYY-MM-DD, defaults to today")
    check_out: Optional[str] = Field(default=None, description="YYYY-MM-DD, defaults to today+1")
    hotel_id: Optional[str] = Field(default=None, description="Override template hotel_id")
    delete_mock_api_key: bool = Field(default=True, description="Delete mocks after run")
    assign_api_key_to_br: bool = Field(default=True, description="Assign API key to BR")
    force_cleanup: bool = Field(default=True, description="Cleanup even on error")
    timeout_seconds: int = Field(default=300, description="Max seconds to wait")
    include_logs: bool = Field(default=False, description="Include execution logs in response")


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
