"""In-memory cache: scenario_id -> provisioning_log.

Populated when a scenario is created. Read when a test result arrives
so the provisioning log can be embedded directly in the test result
and shown in the SB Test Runs dashboard.

Data is lost on server restart (same as test run state), which is fine
since test runs are also in-memory only.
"""
from __future__ import annotations

_cache: dict[str, list[str]] = {}


def store(scenario_id: str, log: list[str]) -> None:
    _cache[scenario_id] = list(log)


def get(scenario_id: str) -> list[str]:
    return _cache.get(scenario_id, [])
