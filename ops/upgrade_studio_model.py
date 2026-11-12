"""Inspect or apply the additive studio cutover using an explicit owner DSN."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    if args.apply_schema and not args.apply:
        parser.error("--apply-schema requires --apply")
    dsn = os.environ.get("HANDRAW_STUDIO_UPGRADE_URL", "")
    if not dsn:
        parser.error(
            "Set HANDRAW_STUDIO_UPGRADE_URL explicitly; the runtime DSN is never selected automatically"
        )
    if args.apply and os.environ.get("HANDRAW_ALLOW_STUDIO_UPGRADE") != "YES":
        parser.error("Apply requires HANDRAW_ALLOW_STUDIO_UPGRADE=YES")
    if not 1 <= args.limit <= 10000:
        parser.error("--limit must be between 1 and 10000")
    from backend.postgres_db import PostgresDatabase
    from backend.studio_upgrade import upgrade_studio_data

    db = PostgresDatabase(dsn)
    try:
        if args.apply and args.apply_schema:
            with db.transaction() as tx:
                tx.execute(
                    (ROOT / "backend/postgres_118_studio_model.sql").read_text(
                        encoding="utf-8"
                    )
                )
        report = upgrade_studio_data(db, apply=args.apply, limit=args.limit)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
