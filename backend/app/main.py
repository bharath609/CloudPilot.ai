"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url

from app.api.routes import costs, health, imports
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.base import Database

logger = logging.getLogger("cloudpilot")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(resolved.database_url)
        app.state.db = database
        app.state.settings = resolved
        if resolved.auto_create_tables:
            if resolved.environment.lower() == "production":
                logger.warning(
                    "CLOUDPILOT_AUTO_CREATE_TABLES is enabled in production; use Alembic instead."
                )
            database.create_all()
        logger.info(
            "%s %s started (env=%s, db=%s)",
            resolved.app_name,
            resolved.app_version,
            resolved.environment,
            _safe_database_url(resolved.database_url),
        )
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        summary="Local-first cloud cost analytics and optimization assistant",
        description=(
            "Ingests cloud billing and utilization CSV exports, validates them with "
            "row-level errors, and stores exact decimal records for transparent "
            "FinOps analysis. CloudPilot AI never modifies cloud resources."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved

    if resolved.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.as_dict()})

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "request_validation_error",
                    "message": "The request payload or parameters are invalid.",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
        )

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {
            "name": resolved.app_name,
            "version": resolved.app_version,
            "docs": "/docs",
            "health": "/api/health",
        }

    app.include_router(health.router)
    app.include_router(imports.router, prefix=resolved.api_prefix)
    app.include_router(costs.router, prefix=resolved.api_prefix)
    return app


def _safe_database_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable database url>"


app = create_app()
