"""Database engine, exact numeric types and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import BigInteger, DateTime, create_engine, event
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class ScaledDecimal(TypeDecorator[Decimal]):
    """Exact decimal stored as a scaled ``BIGINT``.

    SQLite has no native decimal type and SQLAlchemy's ``Numeric`` degrades to
    binary floating point there. Money must never pass through a float, so we
    store ``value * 10**scale`` as an integer and reconstruct the Decimal on
    read. ``SUM()`` over this column is integer addition and therefore exact in
    every supported dialect.
    """

    impl = BigInteger
    cache_ok = True

    def __init__(self, scale: int = 6, **kwargs: Any) -> None:
        if scale < 0 or scale > 9:
            raise ValueError("scale must be between 0 and 9")
        self.scale = scale
        super().__init__(**kwargs)

    def process_bind_param(self, value: Decimal | int | str | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        if not decimal_value.is_finite():
            raise ValueError("non-finite decimal values are not allowed")
        quantum = Decimal(1).scaleb(-self.scale)
        quantized = decimal_value.quantize(quantum, rounding=ROUND_HALF_UP)
        return int(quantized.scaleb(self.scale))

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(int(value)).scaleb(-self.scale)

    def copy(self, **kw: Any) -> ScaledDecimal:
        return ScaledDecimal(scale=self.scale, **kw)


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetime that survives SQLite's naive storage."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Database:
    """Owns the engine and session factory for one application instance."""

    def __init__(self, url: str) -> None:
        self.url = url
        connect_args: dict[str, Any] = {}
        engine_kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}

        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            self._ensure_sqlite_directory(url)
        self.engine = create_engine(url, connect_args=connect_args, **engine_kwargs)

        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

    @staticmethod
    def _ensure_sqlite_directory(url: str) -> None:
        prefix = "sqlite:///"
        if not url.startswith(prefix) or ":memory:" in url:
            return
        raw_path = url[len(prefix) :]
        parent = Path(raw_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def create_all(self) -> None:
        # Imported for its side effect: registers every table on Base.metadata.
        from app.db import models  # noqa: F401

        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


def session_scope(database: Database) -> Iterator[Session]:
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()
