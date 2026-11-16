"""Import upload and inspection endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db
from app.core.config import Settings
from app.core.enums import ImportKind, ImportStatus, Severity
from app.core.errors import (
    EmptyUploadError,
    FileTooLargeError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.db.models import CostRecord, ImportIssue, ImportRecord, ResourceMetric
from app.schemas.imports import (
    CostRecordPreview,
    ImportDetail,
    ImportRecordsResponse,
    ImportResult,
    ImportSummary,
    MetricPreview,
    PaginatedImports,
    PaginatedIssues,
    ValidationIssueOut,
)
from app.services.imports.service import ImportOutcome, ImportService, count_import_issues

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post(
    "/billing",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a generic billing CSV",
)
async def upload_billing(
    file: UploadFile = File(..., description="UTF-8 CSV using the generic billing contract"),
    force: bool = Query(False, description="Import even if this exact file was already uploaded"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ImportResult:
    filename, content = await _read_upload(file, settings)
    outcome = ImportService(db, settings).import_file(
        kind=ImportKind.BILLING,
        filename=filename,
        content=content,
        force=force,
    )
    return _to_result(outcome, settings)


@router.post(
    "/utilization",
    response_model=ImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a generic utilization CSV",
)
async def upload_utilization(
    file: UploadFile = File(..., description="UTF-8 CSV using the generic utilization contract"),
    force: bool = Query(False, description="Import even if this exact file was already uploaded"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ImportResult:
    filename, content = await _read_upload(file, settings)
    outcome = ImportService(db, settings).import_file(
        kind=ImportKind.UTILIZATION,
        filename=filename,
        content=content,
        force=force,
    )
    return _to_result(outcome, settings)


@router.get("", response_model=PaginatedImports, summary="List import attempts")
def list_imports(
    kind: ImportKind | None = Query(None),
    status_filter: ImportStatus | None = Query(None, alias="status"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> PaginatedImports:
    page_size = _page_size(limit, settings)
    filters: list[Any] = []
    if kind is not None:
        filters.append(ImportRecord.kind == kind)
    if status_filter is not None:
        filters.append(ImportRecord.status == status_filter)

    total = int(
        db.scalar(select(func.count()).select_from(ImportRecord).where(*filters)) or 0
    )
    records = list(
        db.scalars(
            select(ImportRecord)
            .where(*filters)
            .order_by(ImportRecord.created_at.desc(), ImportRecord.id.desc())
            .limit(page_size)
            .offset(offset)
        )
    )
    return PaginatedImports(
        items=[ImportSummary.model_validate(record) for record in records],
        total=total,
        limit=page_size,
        offset=offset,
    )


@router.get("/{import_id}", response_model=ImportDetail, summary="Import status and validation summary")
def get_import(
    import_id: int,
    db: Session = Depends(get_db),
) -> ImportDetail:
    record = _get_import(db, import_id)
    return ImportDetail(
        **ImportSummary.model_validate(record).model_dump(),
        content_bytes=record.content_bytes,
        stats=record.stats,
        issue_count=count_import_issues(db, record.id),
        error_count=count_import_issues(db, record.id, Severity.ERROR),
    )


@router.get(
    "/{import_id}/errors",
    response_model=PaginatedIssues,
    summary="Row-level validation issues for an import",
)
def get_import_errors(
    import_id: int,
    severity: Severity | None = Query(None),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> PaginatedIssues:
    record = _get_import(db, import_id)
    page_size = _page_size(limit, settings)

    filters = [ImportIssue.import_id == record.id]
    if severity is not None:
        filters.append(ImportIssue.severity == severity)

    total = int(db.scalar(select(func.count()).select_from(ImportIssue).where(*filters)) or 0)
    issues = list(
        db.scalars(
            select(ImportIssue)
            .where(*filters)
            .order_by(ImportIssue.row_number, ImportIssue.id)
            .limit(page_size)
            .offset(offset)
        )
    )
    return PaginatedIssues(
        items=[ValidationIssueOut.model_validate(issue) for issue in issues],
        total=total,
        limit=page_size,
        offset=offset,
    )


@router.get(
    "/{import_id}/records",
    response_model=ImportRecordsResponse,
    summary="Preview normalized records for audit",
)
def get_import_records(
    import_id: int,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ImportRecordsResponse:
    record = _get_import(db, import_id)
    page_size = _page_size(limit, settings)

    if record.kind is ImportKind.BILLING:
        total = int(
            db.scalar(
                select(func.count())
                .select_from(CostRecord)
                .where(CostRecord.import_id == record.id)
            )
            or 0
        )
        rows: Sequence[Any] = list(
            db.scalars(
                select(CostRecord)
                .where(CostRecord.import_id == record.id)
                .order_by(CostRecord.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        items: list[Any] = [CostRecordPreview.model_validate(row) for row in rows]
    else:
        total = int(
            db.scalar(
                select(func.count())
                .select_from(ResourceMetric)
                .where(ResourceMetric.import_id == record.id)
            )
            or 0
        )
        metric_rows: Sequence[Any] = list(
            db.scalars(
                select(ResourceMetric)
                .where(ResourceMetric.import_id == record.id)
                .order_by(ResourceMetric.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        items = [MetricPreview.model_validate(row) for row in metric_rows]

    return ImportRecordsResponse(
        kind=record.kind,
        items=items,
        total=total,
        limit=page_size,
        offset=offset,
    )


# -- helpers --------------------------------------------------------------
async def _read_upload(file: UploadFile, settings: Settings) -> tuple[str, bytes]:
    filename = Path(file.filename or "").name
    if not filename or not filename.lower().endswith(".csv"):
        raise UnsupportedFileTypeError("Only files with a .csv extension are accepted.")

    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise EmptyUploadError("The uploaded file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise FileTooLargeError(
            f"The uploaded file exceeds the {settings.max_upload_bytes:,}-byte limit."
        )
    return filename, content


def _to_result(outcome: ImportOutcome, settings: Settings) -> ImportResult:
    record = outcome.record
    accepted = record.accepted_row_count
    if record.status is ImportStatus.INVALID:
        message = "Import recorded, but no rows were stored. Review the validation issues."
    elif record.status is ImportStatus.PARTIAL:
        message = (
            f"Imported {accepted} of {record.row_count} rows; "
            f"{record.rejected_row_count} row(s) were rejected."
        )
    elif record.status is ImportStatus.VALID_WITH_WARNINGS:
        message = f"Imported {accepted} rows with {record.warning_count} warning(s)."
    else:
        message = f"Imported {accepted} rows."

    summary = ImportSummary.model_validate(record)
    return ImportResult(
        **summary.model_dump(),
        stats=record.stats,
        issues=[ValidationIssueOut.model_validate(issue) for issue in outcome.issues],
        issues_truncated=outcome.issues_truncated,
        message=message,
    )


def _get_import(db: Session, import_id: int) -> ImportRecord:
    record = db.get(ImportRecord, import_id)
    if record is None:
        raise NotFoundError(f"Import {import_id} was not found.")
    return record


def _page_size(limit: int | None, settings: Settings) -> int:
    return min(limit or settings.default_page_size, settings.max_page_size)
