"""Application settings loaded from environment."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ENV_FILE),
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
    core_app_url: str = "http://hotels-connectivity-core.tajawal-staging.internal"
    business_rules_url: str = "http://hotel-connectivity-br.tajawal-staging.internal"
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
