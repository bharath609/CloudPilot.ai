"""Application settings.

All settings can be overridden with environment variables prefixed with
``CLOUDPILOT_`` or via a ``.env`` file at the repository root.
"""

from __future__ import annotations

from decimal import Decimal
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

    # Waste detection -------------------------------------------------------
    idle_cpu_p95_pct: Decimal = Field(
        default=Decimal("15"),
        ge=0,
        le=100,
        description="A resource is idle only when every CPU p95 sample is below this percentage.",
    )
    idle_memory_p95_pct: Decimal = Field(
        default=Decimal("30"),
        ge=0,
        le=100,
        description="A resource is idle only when every memory p95 sample is below this percentage.",
    )
    rightsize_cpu_avg_pct: Decimal = Field(
        default=Decimal("50"),
        ge=0,
        le=100,
        description="Average CPU must be below this percentage to consider rightsizing.",
    )
    rightsize_memory_avg_pct: Decimal = Field(
        default=Decimal("70"),
        ge=0,
        le=100,
        description="Average memory must be below this percentage to consider rightsizing.",
    )
    min_observation_days: int = Field(default=14, ge=1)
    min_samples: int = Field(default=24, ge=1)
    analysis_cost_days: int = Field(default=30, ge=1, le=366)
    min_monthly_savings: Decimal = Field(default=Decimal("1.00"), ge=0)

    # Price catalogue -------------------------------------------------------
    price_catalogue_path: str = "pricing/catalogue/demo_prices.csv"

    # Forecasting -----------------------------------------------------------
    forecast_horizon_days: int = Field(default=30, ge=1, le=90)
    forecast_holdout_days: int = Field(default=14, ge=1, le=60)
    forecast_moving_average_days: int = Field(default=7, ge=1, le=60)
    forecast_season_length_days: int = Field(default=7, ge=2, le=30)
    forecast_min_history_days: int = Field(default=28, ge=14, le=366)
    forecast_max_history_days: int = Field(default=365, ge=28, le=3650)
    forecast_warning_history_days: int = Field(default=56, ge=14)
    forecast_interval_quantile: Decimal = Field(default=Decimal("0.90"), gt=0, lt=1)

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
