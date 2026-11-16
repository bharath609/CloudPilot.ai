"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "data" / "sample"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        auto_create_tables=True,
        max_upload_bytes=5_000_000,
        max_rows=10_000,
        strict_imports=False,
        log_level="WARNING",
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def sample_path(name: str) -> Path:
    return SAMPLE_DIR / name


def upload(client: TestClient, kind: str, path_or_bytes, *, filename: str | None = None, force: bool = False):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        content = bytes(path_or_bytes)
        name = filename or "upload.csv"
    else:
        path = Path(path_or_bytes)
        content = path.read_bytes()
        name = filename or path.name
    return client.post(
        f"/api/imports/{kind}",
        files={"file": (name, content, "text/csv")},
        params={"force": force},
    )


def import_billing_sample(client: TestClient):
    response = upload(client, "billing", sample_path("billing_sample.csv"))
    assert response.status_code == 201, response.text
    return response


def import_utilization_sample(client: TestClient):
    response = upload(client, "utilization", sample_path("utilization_sample.csv"))
    assert response.status_code == 201, response.text
    return response
