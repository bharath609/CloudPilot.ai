"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.time import utcnow

router = APIRouter(tags=["system"])


def _health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    database_status = "ok"
    try:
        with request.app.state.db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database_status = "error"
    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "database": database_status,
        "time": utcnow().isoformat(),
    }


@router.get("/health", summary="Liveness probe")
def health(request: Request) -> JSONResponse:
    payload = _health(request)
    return JSONResponse(payload, status_code=200 if payload["status"] == "ok" else 503)


@router.get("/api/health", summary="API readiness probe")
def api_health(request: Request) -> JSONResponse:
    payload = _health(request)
    return JSONResponse(payload, status_code=200 if payload["status"] == "ok" else 503)
