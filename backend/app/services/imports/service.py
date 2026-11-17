"""Import orchestration: parse, validate, persist, audit."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ImportKind, ImportStatus, Severity
from app.core.errors import AppError, DuplicateImportError
from app.db.models import CostRecord, ImportIssue, ImportRecord, ResourceMetric
from app.services.ingestion.csv_reader import (
    BILLING_COLUMNS,
    UTILIZATION_COLUMNS,
    CsvStructuralError,
    ParsedCsv,
    parse_csv,
)
from app.services.ingestion.types import (
    CostDraft,
    FieldIssue,
    MetricDraft,
    ValidationOutcome,
)
from app.services.ingestion.validators import validate_billing, validate_utilization

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?$"
)


@dataclass(slots=True)
class ImportOutcome:
    record: ImportRecord
    issues: list[ImportIssue]
    issues_truncated: bool


class ImportService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # -- public API -------------------------------------------------------
    def import_file(
        self,
        *,
        kind: ImportKind,
        filename: str,
        content: bytes,
        source: str = "upload",
        force: bool = False,
    ) -> ImportOutcome:
        started = time.perf_counter()
        digest = hashlib.sha256(content).hexdigest()

        if not force:
            existing = self.db.scalar(
                select(ImportRecord)
                .where(
                    ImportRecord.content_sha256 == digest,
                    ImportRecord.kind == kind,
                )
                .order_by(ImportRecord.id)
                .limit(1)
            )
            if existing is not None:
                raise DuplicateImportError(
                    "This exact file was already imported. Use force=true to import it again.",
                    details={
                        "import_id": existing.id,
                        "kind": existing.kind.value,
                        "status": existing.status.value,
                    },
                )

        required = BILLING_COLUMNS if kind is ImportKind.BILLING else UTILIZATION_COLUMNS

        try:
            parsed = parse_csv(
                content,
                required_columns=required,
                max_rows=self.settings.max_rows,
            )
        except CsvStructuralError as exc:
            return self._persist(
                kind=kind,
                filename=filename,
                content=content,
                digest=digest,
                source=source,
                outcome=ValidationOutcome(
                    drafts=[],
                    issues=exc.issues,
                    row_count=exc.row_count,
                    rejected_rows=exc.row_count,
                    stats={**exc.stats, "structural_failure": True},
                ),
                provider=None,
                started=started,
            )

        if kind is ImportKind.BILLING:
            outcome = validate_billing(
                parsed,
                self.settings,
                existing_keys=self._load_cost_keys(parsed),
            )
            providers = outcome.providers
            provider = providers[0] if len(providers) == 1 else ("mixed" if providers else None)
        else:
            outcome = validate_utilization(
                parsed,
                self.settings,
                existing_keys=self._load_metric_keys(parsed),
                known_resources=self._known_resource_ids(),
            )
            provider = None

        return self._persist(
            kind=kind,
            filename=filename,
            content=content,
            digest=digest,
            source=source,
            outcome=outcome,
            provider=provider,
            started=started,
        )

    # -- persistence ------------------------------------------------------
    def _persist(
        self,
        *,
        kind: ImportKind,
        filename: str,
        content: bytes,
        digest: str,
        source: str,
        outcome: ValidationOutcome,
        provider: str | None,
        started: float,
    ) -> ImportOutcome:
        drafts: list[CostDraft] | list[MetricDraft] = outcome.drafts
        row_count = outcome.row_count
        rejected = outcome.rejected_rows
        status = self._status(outcome)

        if self.settings.strict_imports and outcome.error_count > 0:
            drafts = []
            status = ImportStatus.INVALID
            rejected = row_count
            outcome.issues.append(
                FieldIssue(
                    code="strict_mode_rejected",
                    message=(
                        "Strict import mode is enabled and at least one row failed validation; "
                        "no rows were stored."
                    ),
                    severity=Severity.ERROR,
                )
            )
            outcome.stats["strict_mode"] = True

        accepted = len(drafts)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        stats: dict[str, Any] = {
            **outcome.stats,
            "errors_total": outcome.error_count,
            "warnings_total": outcome.warning_count,
            "duration_ms": duration_ms,
        }

        record = ImportRecord(
            kind=kind,
            filename=filename,
            content_sha256=digest,
            content_bytes=len(content),
            provider=provider,
            status=status,
            row_count=row_count,
            accepted_row_count=accepted,
            rejected_row_count=rejected,
            warning_count=outcome.warning_count,
            currencies=outcome.currencies,
            period_start=outcome.period_start,
            period_end=outcome.period_end,
            source=source,
            stats=stats,
        )

        try:
            self.db.add(record)
            self.db.flush()

            if kind is ImportKind.BILLING:
                self.db.add_all(self._cost_rows(record.id, drafts))
            else:
                self.db.add_all(self._metric_rows(record.id, drafts))

            stored_issues, truncated = self._cap_issues(outcome.issues)
            for issue in stored_issues:
                self.db.add(
                    ImportIssue(
                        import_id=record.id,
                        row_number=issue.row_number,
                        column=issue.column,
                        code=issue.code,
                        severity=issue.severity,
                        message=issue.message[:500],
                        raw_value=issue.raw_value[:200] if issue.raw_value else None,
                    )
                )
            stats["issues_truncated"] = truncated
            stats["issues_stored"] = len(stored_issues)
            record.stats = stats

            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(
                "The import conflicts with existing data (duplicate rows). No rows were stored.",
                code="import_conflict",
                status_code=409,
            ) from exc
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(record)
        stored = list(
            self.db.scalars(
                select(ImportIssue)
                .where(ImportIssue.import_id == record.id)
                .order_by(ImportIssue.id)
                .limit(self.settings.issue_preview_limit)
            )
        )
        return ImportOutcome(record=record, issues=stored, issues_truncated=truncated)

    def _status(self, outcome: ValidationOutcome) -> ImportStatus:
        if not outcome.drafts:
            return ImportStatus.INVALID
        if outcome.rejected_rows > 0:
            return ImportStatus.PARTIAL
        if outcome.warning_count > 0:
            return ImportStatus.VALID_WITH_WARNINGS
        return ImportStatus.VALID

    def _cap_issues(self, issues: list[FieldIssue]) -> tuple[list[FieldIssue], bool]:
        cap = self.settings.max_issues_per_import
        if len(issues) <= cap:
            return issues, False
        hidden = len(issues) - cap
        truncated_issue = FieldIssue(
            code="issues_truncated",
            message=f"{hidden + 1} additional validation issues were not stored.",
            severity=Severity.WARNING,
        )
        return [*issues[: max(cap - 1, 0)], truncated_issue], True

    def _cost_rows(self, import_id: int, drafts: list[CostDraft]) -> list[CostRecord]:
        return [
            CostRecord(
                import_id=import_id,
                source_row_number=draft.row_number,
                usage_date=draft.usage_date,
                provider=draft.provider,
                account_id=draft.account_id,
                service=draft.service,
                resource_id=draft.resource_id,
                region=draft.region,
                environment=draft.environment,
                project=draft.project,
                quantity=draft.quantity,
                usage_unit=draft.usage_unit,
                amount=draft.amount,
                currency=draft.currency,
                tags=draft.tags,
                raw_json=draft.raw,
                sku=draft.sku,
            )
            for draft in drafts
            if isinstance(draft, CostDraft)
        ]

    def _metric_rows(self, import_id: int, drafts: list[MetricDraft]) -> list[ResourceMetric]:
        return [
            ResourceMetric(
                import_id=import_id,
                source_row_number=draft.row_number,
                resource_id=draft.resource_id,
                observed_at=draft.observed_at,
                cpu_avg_pct=draft.cpu_avg_pct,
                cpu_p95_pct=draft.cpu_p95_pct,
                memory_avg_pct=draft.memory_avg_pct,
                memory_p95_pct=draft.memory_p95_pct,
                network_in_bytes=draft.network_in_bytes,
                network_out_bytes=draft.network_out_bytes,
                storage_used_pct=draft.storage_used_pct,
                sample_window_minutes=draft.sample_window_minutes,
            )
            for draft in drafts
            if isinstance(draft, MetricDraft)
        ]

    # -- existing-data lookups -------------------------------------------
    def _load_cost_keys(self, parsed: ParsedCsv) -> set[tuple[object, ...]]:
        dates: list[date] = []
        for row in parsed.rows:
            value = row.values.get("usage_date", "")
            if not value or not _ISO_DATE.match(value):
                continue
            try:
                dates.append(date.fromisoformat(value))
            except ValueError:
                continue
        if not dates:
            return set()

        rows = self.db.execute(
            select(
                CostRecord.usage_date,
                CostRecord.provider,
                CostRecord.account_id,
                CostRecord.service,
                CostRecord.resource_id,
                CostRecord.usage_unit,
                CostRecord.amount,
            ).where(CostRecord.usage_date.between(min(dates), max(dates)))
        ).all()
        return {(row[0], row[1], row[2], row[3], row[4], row[5], row[6]) for row in rows}

    def _load_metric_keys(self, parsed: ParsedCsv) -> set[tuple[object, ...]]:
        resource_ids: set[str] = set()
        timestamps: list[datetime] = []
        for row in parsed.rows:
            resource_id = row.values.get("resource_id", "")
            if resource_id:
                resource_ids.add(resource_id)
            raw_timestamp = row.values.get("timestamp", "")
            if not raw_timestamp or not _ISO_TIMESTAMP.match(raw_timestamp):
                continue
            try:
                value = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00").replace(" ", "T"))
            except ValueError:
                continue
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            timestamps.append(value.astimezone(UTC))
        if not resource_ids or not timestamps:
            return set()

        rows = self.db.execute(
            select(ResourceMetric.resource_id, ResourceMetric.observed_at).where(
                ResourceMetric.resource_id.in_(resource_ids),
                ResourceMetric.observed_at.between(min(timestamps), max(timestamps)),
            )
        ).all()
        return {(row[0], row[1]) for row in rows}

    def _known_resource_ids(self) -> set[str]:
        return set(self.db.scalars(select(CostRecord.resource_id).distinct()))


def count_import_issues(db: Session, import_id: int, severity: Severity | None = None) -> int:
    stmt = select(func.count()).select_from(ImportIssue).where(ImportIssue.import_id == import_id)
    if severity is not None:
        stmt = stmt.where(ImportIssue.severity == severity)
    return int(db.scalar(stmt) or 0)
