"""API contracts for deterministic spend forecasting.

Every monetary value is an exact ``Decimal`` string. Each currency is forecast
separately; projected totals are never combined across currencies.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ConfidenceLevel, ForecastGranularity, ForecastMethod


class ForecastRequest(BaseModel):
    """Optional scope and model configuration for a forecast run."""

    horizon_days: int = Field(default=30, ge=1, le=90)
    holdout_days: int = Field(default=14, ge=1, le=60)
    method: ForecastMethod = ForecastMethod.SEASONAL_NAIVE
    moving_average_days: int = Field(default=7, ge=1, le=60)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    provider: str | None = None
    account_id: str | None = None
    service: str | None = None
    region: str | None = None
    environment: str | None = None
    project: str | None = None


class ForecastPointOut(BaseModel):
    period: date
    predicted_cost: Decimal
    lower_bound: Decimal
    upper_bound: Decimal


class ForecastEvaluation(BaseModel):
    """Held-out error metrics and their explicit limits."""

    method: ForecastMethod
    history_days: int
    train_days: int
    holdout_days: int
    evaluated_points: int
    mae: Decimal
    rmse: Decimal
    bias: Decimal
    mape_pct: Decimal | None = None
    mape_excluded_points: int = 0
    interval_quantile: Decimal
    interval_width: Decimal
    confidence: ConfidenceLevel
    warnings: list[str] = Field(default_factory=list)


class ForecastSeries(BaseModel):
    currency: str
    history_start: date
    history_end: date
    horizon_start: date
    horizon_end: date
    history_days: int
    points: list[ForecastPointOut] = Field(default_factory=list)
    evaluation: ForecastEvaluation
    projected_total: Decimal
    projected_lower: Decimal
    projected_upper: Decimal
    notes: list[str] = Field(default_factory=list)


class ForecastRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    method: ForecastMethod
    granularity: ForecastGranularity
    reference_date: date | None = None
    history_start: date | None = None
    history_end: date | None = None
    horizon_start: date | None = None
    horizon_end: date | None = None
    currency: str | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    series_count: int
    evaluation: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration_ms: int
    created_at: datetime
    completed_at: datetime | None = None


class ForecastResult(BaseModel):
    run: ForecastRunSummary
    series: list[ForecastSeries] = Field(default_factory=list)


class ForecastListResponse(BaseModel):
    run: ForecastRunSummary | None = None
    series: list[ForecastSeries] = Field(default_factory=list)
    total: int
