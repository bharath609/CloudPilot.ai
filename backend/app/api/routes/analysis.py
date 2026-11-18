"""Waste detection endpoints: run analysis and inspect findings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db
from app.core.config import Settings
from app.core.enums import FindingStatus, FindingType
from app.core.errors import NotFoundError
from app.db.models import AnalysisRun, Finding, FindingDecision, SavingsScenario
from app.schemas.analysis import (
    AnalysisRunResult,
    AnalysisRunSummary,
    AnalysisScopeRequest,
    FindingListResponse,
    FindingOut,
    SavingsScenarioOut,
)
from app.schemas.decisions import FindingDecisionOut
from app.services.analysis import AnalysisOutcome, AnalysisScope, run_analysis
from app.services.decisions import latest_for

router = APIRouter(tags=["analysis"])


@router.post(
    "/analysis/run",
    response_model=AnalysisRunResult,
    summary="Run deterministic waste detection over imported billing and utilization data",
)
def create_analysis_run(
    payload: AnalysisScopeRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> AnalysisRunResult:
    values = payload or AnalysisScopeRequest()
    scope = AnalysisScope(**values.model_dump())
    try:
        outcome = run_analysis(db, settings, scope)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _result(outcome)


@router.get(
    "/findings",
    response_model=FindingListResponse,
    summary="List findings from the latest analysis run (or a specific run)",
)
def list_findings(
    run_id: int | None = Query(None, ge=1),
    finding_type: FindingType | None = Query(None),
    status_filter: FindingStatus | None = Query(None, alias="status"),
    currency: str | None = Query(None, pattern=r"^[A-Za-z]{3}$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> FindingListResponse:
    run = _get_run(db, run_id) if run_id is not None else _latest_run(db)
    page_size = min(limit or settings.default_page_size, settings.max_page_size)
    if run is None:
        return FindingListResponse(run=None, items=[], total=0, limit=page_size, offset=offset)

    filters: list[Any] = [Finding.run_id == run.id]
    if finding_type is not None:
        filters.append(Finding.finding_type == finding_type)
    if status_filter is not None:
        filters.append(Finding.status == status_filter)
    if currency:
        filters.append(Finding.currency == currency.upper())

    total = int(db.scalar(select(func.count()).select_from(Finding).where(*filters)) or 0)
    rows = list(
        db.scalars(
            select(Finding)
            .where(*filters)
            .order_by(Finding.estimated_monthly_savings.desc(), Finding.id)
            .limit(page_size)
            .offset(offset)
        )
    )
    scenarios = _scenarios_for(db, [row.id for row in rows])
    decisions = latest_for(db, [row.id for row in rows])
    return FindingListResponse(
        run=AnalysisRunSummary.model_validate(run),
        items=[
            _finding_out(row, scenarios.get(row.id), decisions.get(row.id)) for row in rows
        ],
        total=total,
        limit=page_size,
        offset=offset,
    )


@router.get("/findings/{finding_id}", response_model=FindingOut, summary="Finding detail and scenario")
def get_finding(finding_id: int, db: Session = Depends(get_db)) -> FindingOut:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError(f"Finding {finding_id} was not found.")
    scenario = db.scalar(select(SavingsScenario).where(SavingsScenario.finding_id == finding.id))
    decision = latest_for(db, [finding.id]).get(finding.id)
    return _finding_out(finding, scenario, decision)


# -- helpers --------------------------------------------------------------
def _result(outcome: AnalysisOutcome) -> AnalysisRunResult:
    return AnalysisRunResult(
        run=AnalysisRunSummary.model_validate(outcome.run),
        findings=[
            _finding_out(bundle.finding, bundle.scenario, None) for bundle in outcome.bundles
        ],
    )


def _finding_out(
    finding: Finding,
    scenario: SavingsScenario | None,
    decision: FindingDecision | None,
) -> FindingOut:
    item = FindingOut.model_validate(finding)
    if scenario is not None:
        item.scenario = SavingsScenarioOut.model_validate(scenario)
    if decision is not None:
        item.decision = FindingDecisionOut.model_validate(decision)
    return item


def _latest_run(db: Session) -> AnalysisRun | None:
    return db.scalar(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(1))


def _get_run(db: Session, run_id: int) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise NotFoundError(f"Analysis run {run_id} was not found.")
    return run


def _scenarios_for(db: Session, finding_ids: list[int]) -> dict[int, SavingsScenario]:
    if not finding_ids:
        return {}
    rows = db.scalars(select(SavingsScenario).where(SavingsScenario.finding_id.in_(finding_ids)))
    return {row.finding_id: row for row in rows}
