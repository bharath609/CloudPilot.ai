"""Read-only resource health inventory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db
from app.api.routes.costs import cost_scope
from app.core.config import Settings
from app.schemas.resources import ResourceHealthResponse
from app.services.analytics import CostScope
from app.services.resources import resource_health

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get(
    "",
    response_model=ResourceHealthResponse,
    summary="Utilization, observation window, ownership and window cost per resource",
)
def list_resources(
    scope: CostScope = Depends(cost_scope),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ResourceHealthResponse:
    page_size = min(limit or settings.default_page_size, settings.max_page_size)
    return resource_health(db, settings, scope, limit=page_size, offset=offset)
