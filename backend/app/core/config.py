"""Application settings.

All settings can be overridden with environment variables prefixed with
``CLOUDPILOT_`` or via a ``.env`` file at the repository root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Typed, environment-driven configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CLOUDPILOT_",
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "CloudPilot AI"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api"
    log_level: str = "INFO"

    # Persistence -----------------------------------------------------------
    database_url: str = f"sqlite:///{(REPO_ROOT / 'cloudpilot.db').as_posix()}"
    auto_create_tables: bool = True

    # HTTP ------------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_page_size: int = Field(default=200, gt=0, le=1000)
    default_page_size: int = Field(default=50, gt=0, le=1000)

    # Ingestion limits ------------------------------------------------------
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_rows: int = Field(default=200_000, gt=0)
    max_issues_per_import: int = Field(default=1_000, gt=0)
    issue_preview_limit: int = Field(default=50, gt=0)

    # Ingestion policy ------------------------------------------------------
    strict_imports: bool = Field(
        default=False,
        description="When true, a single row error rejects the entire import.",
    )
    allowed_currencies: str = "USD,EUR,GBP,INR,CAD,AUD"
    known_usage_units: str = (
        "Hrs,Hours,GB,GB-Mo,GB-Month,Requests,Invocations,Count,Units,"
        "vCPU-Hrs,IOPS,MB,Months,Days,LCU-Hrs"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_currency_set(self) -> frozenset[str]:
        return frozenset(item.strip().upper() for item in self.allowed_currencies.split(",") if item.strip())

    @property
    def known_usage_unit_set(self) -> frozenset[str]:
        return frozenset(item.strip().lower() for item in self.known_usage_units.split(",") if item.strip())

    @property
    def is_test(self) -> bool:
        return self.environment.lower() in {"test", "testing"}


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, cached for FastAPI dependencies."""

    return Settings()
