"""AI advisor endpoints: generate and inspect evidence-bound reports.

The advisor is optional and disabled by default. Every response is stored
immutably together with the exact bounded evidence package that was eligible to
leave the machine, so a reviewer can reproduce or reject the explanation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_llm_client
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.models import AdvisorReport
from app.llm.client import OpenAICompatibleClient
from app.schemas.advisor import (
    AdvisorOutputOut,
    AdvisorReportDetail,
    AdvisorReportListResponse,
    AdvisorReportSummary,
    ReportGenerateRequest,
)
from app.services.advisor import ReportOutcome, generate_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post(
    "/generate",
    response_model=AdvisorReportDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an evidence-bound AI explanation, or a deterministic fallback",
)
def create_report(
    payload: ReportGenerateRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    client: OpenAICompatibleClient | None = Depends(get_llm_client),
) -> AdvisorReportDetail:
    values = payload or ReportGenerateRequest()
    try:
        outcome = generate_report(db, settings, values, client=client)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _detail(outcome)


@router.get(
    "",
    response_model=AdvisorReportListResponse,
    summary="List stored advisor reports, newest first",
)
def list_reports(
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> AdvisorReportListResponse:
    page_size = min(limit or settings.default_page_size, settings.max_page_size)
    total = int(db.scalar(select(func.count()).select_from(AdvisorReport)) or 0)
    rows = list(
        db.scalars(
            select(AdvisorReport)
            .order_by(AdvisorReport.id.desc())
            .limit(page_size)
            .offset(offset)
        )
    )
    return AdvisorReportListResponse(
        items=[AdvisorReportSummary.model_validate(row) for row in rows],
        total=total,
        limit=page_size,
        offset=offset,
    )


@router.get(
    "/{report_id}",
    response_model=AdvisorReportDetail,
    summary="One report with its validated output and evidence package",
)
def get_report(report_id: int, db: Session = Depends(get_db)) -> AdvisorReportDetail:
    report = db.get(AdvisorReport, report_id)
    if report is None:
        raise NotFoundError(f"Advisor report {report_id} was not found.")
    return _detail(ReportOutcome(report=report, output=AdvisorOutputOut.model_validate(report.output)))


# -- helpers --------------------------------------------------------------
def _detail(outcome: ReportOutcome) -> AdvisorReportDetail:
    report = outcome.report
    summary = AdvisorReportSummary.model_validate(report)
    return AdvisorReportDetail(
        **summary.model_dump(),
        output=outcome.output,
        evidence=report.evidence if isinstance(report.evidence, dict) else {},
        notes=list(report.notes or []),
        warnings=list(report.warnings or []),
    )
