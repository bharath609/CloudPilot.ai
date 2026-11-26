"""Application configuration for CloudPilot AI.

Reads from environment variables with safe local-first defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

# Project root = .../CloudPilot.ai
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
ROOT_DIR = BACKEND_DIR.parent


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


HOST = _env("CLOUDPILOT_HOST", "127.0.0.1")
PORT = int(_env("CLOUDPILOT_PORT", "8000"))
DATABASE_PATH = Path(_env("CLOUDPILOT_DB", str(ROOT_DIR / "cloudpilot.db")))
FRONTEND_DIST = Path(_env("CLOUDPILOT_FRONTEND_DIST", str(ROOT_DIR / "frontend" / "dist")))
DATA_FRESHNESS_HOURS = int(_env("CLOUDPILOT_FRESHNESS_HOURS", "24"))
