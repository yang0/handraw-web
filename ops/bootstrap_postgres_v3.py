#!/usr/bin/env python3
"""Initialize an empty PostgreSQL database from the Handraw V3 baseline.

Usage:
  python -m ops.bootstrap_postgres_v3
  HANDRAW_ALLOW_PG_BOOTSTRAP=YES HANDRAW_DATABASE_URL='postgresql://...' \
      python -m ops.bootstrap_postgres_v3 --apply

The target public schema must contain zero user tables.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASELINE_PATH = ROOT / "backend" / "postgres_v3_baseline.sql"
MIGRATIONS = (
    ROOT / "backend" / "postgres_110_home_scenario_ratio.sql",
    ROOT / "backend" / "postgres_111_payment_billing.sql",
    ROOT / "backend" / "postgres_112_cold_start_registry.sql",
    ROOT / "backend" / "postgres_113_forum_reply_notifications.sql",
    ROOT / "backend" / "postgres_114_growth_events.sql",
)


def bootstrap(*, dsn: str, apply: bool) -> dict:
    ddl = BASELINE_PATH.read_text(encoding="utf-8")
    migrations = [path.read_text(encoding="utf-8") for path in MIGRATIONS]
    all_sql = "\n".join([ddl, *migrations])
    report = {
        "ok": True, "mode": "fresh-v3-schema",
        "tables": len(re.findall(r"^CREATE TABLE (?:IF NOT EXISTS )?public\.", all_sql, re.M)),
        "foreignKeys": len(re.findall(r"\bREFERENCES public\.", all_sql)),
        "indexes": len(re.findall(r"^CREATE (?:UNIQUE )?INDEX ", all_sql, re.M)),
        "migrationVersions": len(re.findall(r"^    \(\d+, '\d{3}_", ddl, re.M)) + len(migrations),
        "dryRun": not apply, "userDataTransferred": False,
        "destructiveOperations": False,
    }
    if not apply:
        return report
    if os.environ.get("HANDRAW_ALLOW_PG_BOOTSTRAP") != "YES":
        raise RuntimeError("Set HANDRAW_ALLOW_PG_BOOTSTRAP=YES to initialize an empty PostgreSQL database")
    if not dsn:
        raise RuntimeError("HANDRAW_DATABASE_URL must point to an empty PostgreSQL database")

    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from backend.home_scenarios import seed_default_home_scenarios_hook
    from backend.postgres_db import PgConnection

    if conninfo_to_dict(dsn).get("dbname") in (None, "postgres", "template0", "template1", ""):
        raise RuntimeError("Refusing to initialize a default/system PostgreSQL database")
    with psycopg.connect(dsn, connect_timeout=5) as pg:
        with pg.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute("SET LOCAL statement_timeout='120s'")
            cur.execute("SET LOCAL search_path TO public, pg_catalog")
            cur.execute("SELECT pg_advisory_xact_lock(186, 100)")
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'f')
                )
            """)
            if cur.fetchone()[0]:
                raise RuntimeError("Target is not empty: refusing to overwrite or merge any existing schema")
            cur.execute(ddl)
            for migration in migrations:
                cur.execute(migration)
        seed_default_home_scenarios_hook(PgConnection(pg))
    return {**report, "created": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialize an EMPTY PostgreSQL DB from the fresh Handraw V3 schema"
    )
    parser.add_argument("--apply", action="store_true", help="create schema after safety checks")
    args = parser.parse_args(argv)
    try:
        report = bootstrap(
            dsn=os.environ.get("HANDRAW_DATABASE_URL", ""), apply=args.apply
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
