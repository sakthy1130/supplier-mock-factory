"""Current-environment selection (dev | stg) via a contextvar.

The active env is resolved per request from the ``X-SMF-Env`` header (middleware in
main.py) and per background job from the scenario's stored ``env``. ``get_settings()``
and other env-aware helpers read ``get_current_env()`` so callers don't have to thread
the env through every layer.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token

SUPPORTED_ENVS: tuple[str, ...] = ("dev", "stg")
DEFAULT_ENV: str = "dev"

_current_env: ContextVar[str] = ContextVar("smf_current_env", default=DEFAULT_ENV)


def normalize_env(value: str | None) -> str:
    """Return a valid env, falling back to DEFAULT_ENV for unknown/empty input."""
    if not value:
        return DEFAULT_ENV
    candidate = value.strip().lower()
    return candidate if candidate in SUPPORTED_ENVS else DEFAULT_ENV


def get_current_env() -> str:
    return _current_env.get()


def set_current_env(value: str | None) -> Token[str]:
    """Set the active env; returns a token for reset()."""
    return _current_env.set(normalize_env(value))


def reset_current_env(token: Token[str]) -> None:
    _current_env.reset(token)


@contextmanager
def use_env(value: str | None):
    """Scope a block to a specific env (used by CLI scripts / background jobs)."""
    token = set_current_env(value)
    try:
        yield get_current_env()
    finally:
        reset_current_env(token)
