"""Downloadable exports generated from stored, deterministic records.

The CSV is sanitized against spreadsheet formula injection and the Markdown
report carries assumptions, warnings, lineage and the synthetic-data notice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.exports import findings_csv, summary_markdown

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get(
    "/findings.csv",
    response_class=Response,
    summary="Findings as an Excel-safe CSV (one row per finding, per currency)",
)
def export_findings_csv(
    run_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> Response:
    filename, content = findings_csv(db, run_id)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/summary.md",
    response_class=Response,
    summary="Cost optimization report as Markdown, with decisions and lineage",
)
def export_summary_markdown(
    run_id: int | None = Query(None, ge=1),
    forecast_run_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> Response:
    filename, content = summary_markdown(db, run_id=run_id, forecast_run_id=forecast_run_id)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
