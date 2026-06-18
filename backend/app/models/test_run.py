"""Pydantic models for live test-run tracking."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TestStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ABORTED = "ABORTED"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class HttpDetails(BaseModel):
    """Captured HTTP call details attached on failure."""

    method: Optional[str] = None
    url: Optional[str] = None
    request_body: Optional[str] = None
    response_status: Optional[int] = None
    response_body: Optional[str] = None


class StepNode(BaseModel):
    """One Allure @Step in the captured step tree (recursive)."""

    name: str
    status: Optional[str] = None  # PASSED | FAILED | BROKEN | SKIPPED
    duration_ms: int = 0
    steps: list["StepNode"] = Field(default_factory=list)


class TestResult(BaseModel):
    """Single test result posted by the JUnit TestExecutionListener."""

    scenario_id: Optional[str] = Field(default=None, description="SMF scenario UUID")
    test_class: str
    test_method: str
    status: TestStatus
    duration_ms: int = Field(ge=0)
    # Allure @Step tree for Allure-style drill-down on the dashboard
    steps: list[StepNode] = Field(default_factory=list)
    failure_message: Optional[str] = None
    stack_trace: Optional[str] = None
    failed_step: Optional[str] = None
    http_details: Optional[HttpDetails] = None
    posted_at: Optional[datetime] = None
    # Injected server-side from provisioning_log_cache when scenario_id is known
    provisioning_log: list[str] = Field(default_factory=list)


class ResultStepsRequest(BaseModel):
    """Allure @Step tree for one test, posted separately and merged by test_method."""

    test_method: str
    steps: list[StepNode] = Field(default_factory=list)


class TestRunStartResponse(BaseModel):
    run_id: str
    status: RunStatus = RunStatus.RUNNING
    started_at: datetime


class TestRunState(BaseModel):
    run_id: str
    status: RunStatus
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[TestResult] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
