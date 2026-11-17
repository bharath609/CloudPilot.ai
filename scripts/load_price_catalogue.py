"""Load or refresh the sourced price catalogue.

Run from the repository root:

    python scripts/load_price_catalogue.py
    python scripts/load_price_catalogue.py --path pricing/catalogue/demo_prices.csv
    python scripts/load_price_catalogue.py --database-url postgresql+psycopg://...

The loader is idempotent. It performs no network calls: the CSV is the source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.db.base import Database  # noqa: E402
from app.services.prices import (  # noqa: E402
    PriceCatalogueError,
    load_price_catalogue,
    resolve_catalogue_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Load a CloudPilot AI price catalogue.")
    parser.add_argument("--path", default=None, help="Catalogue CSV path.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy URL. Defaults to CLOUDPILOT_DATABASE_URL or the local SQLite file.",
    )
    args = parser.parse_args()

    settings = Settings(
        **(  # type: ignore[arg-type]
            {"database_url": args.database_url} if args.database_url else {}
        )
    )
    catalogue = resolve_catalogue_path(settings, args.path)
    database = Database(settings.database_url)
    database.create_all()
    session = database.session_factory()
    try:
        result = load_price_catalogue(session, catalogue)
    except PriceCatalogueError as exc:
        for message in exc.messages:
            print(f"error: {message}")
        return 1
    finally:
        session.close()
        database.dispose()

    print(
        f"prices: inserted={result.inserted} updated={result.updated} "
        f"total={result.total} synthetic={result.synthetic} real={result.real} "
        f"path={catalogue}"
    )
    if result.synthetic:
        print("warning: synthetic demo prices are loaded; they are not vendor quotes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
