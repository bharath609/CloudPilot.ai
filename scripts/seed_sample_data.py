"""Import the synthetic sample files into a local database.

Run from the repository root:

    python scripts/seed_sample_data.py
    python scripts/seed_sample_data.py --force        # re-import even if hashes match
    python scripts/seed_sample_data.py --database-url postgresql+psycopg://...

This script writes only to the configured database. It performs no cloud calls.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.enums import ImportKind, ImportStatus  # noqa: E402
from app.db.base import Database  # noqa: E402
from app.db.models import ImportRecord  # noqa: E402
from app.services.imports.service import ImportService  # noqa: E402

SAMPLE_DIR = REPO_ROOT / "data" / "sample"
FILES: list[tuple[ImportKind, str]] = [
    (ImportKind.BILLING, "billing_sample.csv"),
    (ImportKind.UTILIZATION, "utilization_sample.csv"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed CloudPilot AI with synthetic sample data.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy URL. Defaults to CLOUDPILOT_DATABASE_URL or the local SQLite file.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Import even when an identical file hash already exists.",
    )
    args = parser.parse_args()

    settings = Settings(
        **(  # type: ignore[arg-type]
            {"database_url": args.database_url} if args.database_url else {}
        )
    )
    database = Database(settings.database_url)
    database.create_all()

    session = database.session_factory()
    failures = 0
    try:
        for kind, filename in FILES:
            path = SAMPLE_DIR / filename
            if not path.exists():
                print(f"missing sample file: {path}")
                failures += 1
                continue
            content = path.read_bytes()
            service = ImportService(session, settings)
            existing = session.scalar(
                select(ImportRecord)
                .where(
                    ImportRecord.content_sha256 == _sha256(content),
                    ImportRecord.kind == kind,
                )
                .limit(1)
            )
            if existing is not None and not args.force:
                print(
                    f"skip {filename}: already imported as id={existing.id} "
                    f"(status={existing.status.value}). Use --force to re-import."
                )
                continue

            outcome = service.import_file(
                kind=kind,
                filename=filename,
                content=content,
                source="sample",
                force=args.force,
            )
            record = outcome.record
            print(
                f"{kind.value}: import_id={record.id} status={record.status.value} "
                f"rows={record.row_count} accepted={record.accepted_row_count} "
                f"rejected={record.rejected_row_count} warnings={record.warning_count} "
                f"currencies={','.join(record.currencies) or '-'}"
            )
            if record.status in {ImportStatus.INVALID, ImportStatus.PARTIAL, ImportStatus.FAILED}:
                failures += 1
    finally:
        session.close()
        database.dispose()

    if failures:
        print("Sample seeding finished with problems. Check the validation issues in the API.")
        return 1
    print("Sample seeding complete. All data is synthetic.")
    return 0


def _sha256(content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
