"""Append-only human review decisions on findings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db
from app.core.config import Settings
from app.core.enums import DecisionKind
from app.schemas.decisions import (
    DecisionListItem,
    DecisionListResponse,
    DecisionRequest,
    FindingDecisionOut,
)
from app.services.decisions import list_decisions, record_decision

router = APIRouter(tags=["decisions"])


@router.post(
    "/findings/{finding_id}/decision",
    response_model=FindingDecisionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a human decision for one finding (append-only)",
)
def create_decision(
    finding_id: int,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
) -> FindingDecisionOut:
    try:
        decision = record_decision(db, finding_id, payload)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return FindingDecisionOut.model_validate(decision)


@router.get(
    "/decisions",
    response_model=DecisionListResponse,
    summary="Review history across all findings, newest first",
)
def get_decisions(
    decision: DecisionKind | None = Query(None),
    finding_id: int | None = Query(None, ge=1),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> DecisionListResponse:
    page_size = min(limit or settings.default_page_size, settings.max_page_size)
    items, total = list_decisions(
        db,
        decision=decision,
        finding_id=finding_id,
        limit=page_size,
        offset=offset,
    )
    return DecisionListResponse(
        items=[DecisionListItem.model_validate(item) for item in items],
        total=total,
        limit=page_size,
        offset=offset,
    )
