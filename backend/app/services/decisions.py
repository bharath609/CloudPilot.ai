"""Append-only decision recording and lookup."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import DecisionKind
from app.core.errors import AppError, NotFoundError
from app.db.models import Finding, FindingDecision
from app.schemas.decisions import DecisionListItem, DecisionRequest

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def _clean(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    text = _CONTROL.sub(" ", value)
    text = _WHITESPACE.sub(" ", text).strip()
    return text[:limit] or None


def record_decision(
    db: Session, finding_id: int, request: DecisionRequest
) -> FindingDecision:
    """Append a decision to an existing finding.

    Findings are immutable, so this never updates the finding row. Re-submitting
    is allowed and creates a new history entry; the newest row is authoritative.
    """

    finding = db.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError(f"Finding {finding_id} was not found.")
    actor = _clean(request.actor, limit=80)
    if not actor:
        raise AppError(
            "actor must contain visible characters.",
            code="invalid_actor",
            status_code=422,
        )
    decision = FindingDecision(
        finding_id=finding.id,
        decision=request.decision,
        actor=actor,
        note=_clean(request.note, limit=500),
    )
    db.add(decision)
    db.flush()
    return decision


def latest_for(db: Session, finding_ids: list[int]) -> dict[int, FindingDecision]:
    """Newest decision per finding. The table is append-only, so max(id) wins."""

    if not finding_ids:
        return {}
    newest = (
        select(func.max(FindingDecision.id))
        .where(FindingDecision.finding_id.in_(finding_ids))
        .group_by(FindingDecision.finding_id)
        .scalar_subquery()
    )
    rows = db.scalars(select(FindingDecision).where(FindingDecision.id.in_(newest)))
    return {row.finding_id: row for row in rows}


def list_decisions(
    db: Session,
    *,
    decision: DecisionKind | None = None,
    finding_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DecisionListItem], int]:
    filters: list[Any] = []
    if decision is not None:
        filters.append(FindingDecision.decision == decision)
    if finding_id is not None:
        filters.append(FindingDecision.finding_id == finding_id)

    total = int(
        db.scalar(select(func.count()).select_from(FindingDecision).where(*filters)) or 0
    )
    rows = db.execute(
        select(FindingDecision, Finding)
        .join(Finding, Finding.id == FindingDecision.finding_id)
        .where(*filters)
        .order_by(FindingDecision.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        DecisionListItem(
            id=item.id,
            finding_id=item.finding_id,
            decision=item.decision,
            actor=item.actor,
            note=item.note,
            created_at=item.created_at,
            finding_type=finding.finding_type,
            resource_id=finding.resource_id,
            service=finding.service,
            environment=finding.environment,
            project=finding.project,
            currency=finding.currency,
            risk=finding.risk,
            estimated_monthly_savings=finding.estimated_monthly_savings,
            cost_window_start=finding.cost_window_start,
            cost_window_end=finding.cost_window_end,
        )
        for item, finding in rows
    ]
    return items, total
