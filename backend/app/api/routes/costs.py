"""Spend analytics endpoints: summary, breakdown and trends."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.enums import CostDimension, TrendGranularity
from app.core.errors import AppError
from app.schemas.costs import CostBreakdown, CostSummary, CostTrends
from app.services.analytics import CostScope, breakdown, summarize, trends

router = APIRouter(prefix="/costs", tags=["costs"])


def cost_scope(
    start: date | None = Query(None, description="Inclusive start of the usage-date window"),
    end: date | None = Query(None, description="Inclusive end of the usage-date window"),
    currency: str | None = Query(None, pattern=r"^[A-Za-z]{3}$", description="ISO 4217 code"),
    provider: str | None = Query(None),
    account_id: str | None = Query(None),
    service: str | None = Query(None),
    region: str | None = Query(None),
    environment: str | None = Query(None),
    project: str | None = Query(None),
) -> CostScope:
    if start is not None and end is not None and start > end:
        raise AppError(
            "'start' must be on or before 'end'.",
            code="invalid_date_range",
            status_code=400,
            details={"start": start.isoformat(), "end": end.isoformat()},
        )
    return CostScope(
        start=start,
        end=end,
        currency=currency,
        provider=provider,
        account_id=account_id,
        service=service,
        region=region,
        environment=environment,
        project=project,
    )


@router.get("/summary", response_model=CostSummary, summary="Spend overview by currency")
def get_summary(
    scope: CostScope = Depends(cost_scope),
    db: Session = Depends(get_db),
) -> CostSummary:
    return summarize(db, scope)


@router.get(
    "/breakdown",
    response_model=CostBreakdown,
    summary="Spend breakdown by service, project, region, environment, provider, account or resource",
)
def get_breakdown(
    scope: CostScope = Depends(cost_scope),
    dimension: CostDimension = Query(CostDimension.SERVICE),
    limit: int = Query(10, ge=1, le=100, description="Rows per currency, largest first"),
    db: Session = Depends(get_db),
) -> CostBreakdown:
    return breakdown(db, scope, dimension=dimension, limit=limit)


@router.get("/trends", response_model=CostTrends, summary="Daily or monthly spend trend")
def get_trends(
    scope: CostScope = Depends(cost_scope),
    granularity: TrendGranularity = Query(TrendGranularity.DAY),
    db: Session = Depends(get_db),
) -> CostTrends:
    return trends(db, scope, granularity=granularity)
