"""Application settings loaded from per-environment files.

Layering (later overrides earlier): legacy ``.env`` → ``.env.shared`` → ``.env.{env}``.
``get_settings()`` returns the Settings for the active env (see app.env_context); pass an
explicit env to target another one (e.g. teardown pinned to a scenario's stored env).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.env_context import get_current_env, normalize_env

BACKEND_DIR = Path(__file__).resolve().parents[1]
BACKEND_ENV_FILE = BACKEND_DIR / ".env"


def _env_files(env: str) -> tuple[str, ...]:
    """Ordered dotenv files for an env; later files win. Only existing files are kept."""
    candidates = [
        BACKEND_ENV_FILE,               # legacy single-file fallback (base)
        BACKEND_DIR / ".env.shared",    # values common to all envs
        BACKEND_DIR / f".env.{env}",    # env-specific (highest priority)
    ]
    return tuple(str(p) for p in candidates if p.exists())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mock_server_url: str = ""
    logs_api_url: str = ""
    quickwit_logs_api_url: str = ""
    mapping_service_url: str = ""
    mapping_api_key: str = ""
    crawla_api_url: str = ""
    crawla_api_key: str = ""
    core_app_url: str = ""
    business_rules_url: str = ""
    backoffice_url: str = ""
    config_manager_url: str = ""

    backoffice_token: str = ""
    tenant_id: str = ""
    backoffice_username: str = ""
    backoffice_password: str = ""

    hbs_reference_contract_id: str = ""
    exp_reference_contract_id: str = ""
    rhk_reference_contract_id: str = ""
    chc_reference_contract_id: str = ""
    api_key_template_uid: str = ""

    database_url: str = "sqlite:///./smf.db"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    env: str = ""  # populated by get_settings so callers can read settings.env

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def _build_settings(env: str) -> Settings:
    settings = Settings(_env_file=_env_files(env))
    settings.env = env
    return settings


def get_settings(env: str | None = None) -> Settings:
    """Settings for the given env; defaults to the active env (contextvar)."""
    resolved = normalize_env(env) if env is not None else get_current_env()
    return _build_settings(resolved)


def clear_settings_cache() -> None:
    """Drop cached Settings (tests that mutate env files)."""
    _build_settings.cache_clear()
