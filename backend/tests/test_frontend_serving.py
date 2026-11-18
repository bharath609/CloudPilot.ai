"""Optional static serving of the built frontend from the same origin."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _settings(tmp_path: Path, dist: Path | None = None) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'serve.db').as_posix()}",
        auto_create_tables=True,
        log_level="WARNING",
        frontend_dist_dir=str(dist) if dist is not None else str(tmp_path / "missing"),
    )


def test_root_is_json_without_a_build(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "CloudPilot AI"
        assert body["docs"] == "/docs"


def test_built_frontend_is_served_with_the_api(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>CloudPilot</title><div id=root></div>", encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

    with TestClient(create_app(_settings(tmp_path, dist))) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.headers["content-type"].startswith("text/html")
        assert "id=root" in root.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "console.log" in asset.text

        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/filters").status_code == 200
        assert client.get("/nope").status_code == 404
