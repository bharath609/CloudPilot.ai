"""Discoverable filter values and data freshness."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.filters import FilterOptions
from app.services.filters import filter_options

router = APIRouter(prefix="/filters", tags=["filters"])


@router.get(
    "",
    response_model=FilterOptions,
    summary="Distinct filter values, billing window and data freshness",
)
def get_filters(db: Session = Depends(get_db)) -> FilterOptions:
    return filter_options(db)
