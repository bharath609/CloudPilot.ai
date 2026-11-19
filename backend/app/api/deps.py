"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.llm.client import OpenAICompatibleClient, create_client


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_llm_client(settings: Settings = Depends(get_app_settings)) -> OpenAICompatibleClient | None:
    """Return a provider client only when the advisor is explicitly enabled.

    The advisor is disabled by default, so no client is constructed and no data
    can leave the machine. Tests override this dependency with a stub client.
    """
    if not settings.llm_enabled:
        return None
    return create_client(settings)


def get_db(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.db.session_factory()
    try:
        yield session
    finally:
        session.close()
