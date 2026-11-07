#!/usr/bin/env python3
"""Bootstrap a FRESH Handraw V3 PostgreSQL database, never migrate user data.

The site has many auxiliary tables besides the V3 generation model. Build a
temporary, completely empty SQLite *schema* from the current migrations to
derive the complete table/column/index/FK manifest, but do NOT copy any users
or content. Build actual PostgreSQL tables/identity columns/FKs natively, then
install the V3 PostgreSQL functions, checks, triggers and index semantics.

Usage:
  python -m ops.bootstrap_postgres_v3
  HANDRAW_ALLOW_PG_BOOTSTRAP=YES HANDRAW_DATABASE_URL='postgresql://...' \
      python -m ops.bootstrap_postgres_v3 --apply

The target public schema MUST contain zero user tables. This never drops or
overwrites an existing table and never reads/updates SQLite user data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db import Database
from backend.postgres_v3_native import NATIVE_V3_SQL
from ops import sqlite_to_postgres as staging


POSTGRES_JSON_HELPERS_SQL = r"""
CREATE OR REPLACE FUNCTION json_valid(t text) RETURNS integer
LANGUAGE plpgsql IMMUTABLE AS $func$
BEGIN
  IF t IS NULL THEN RETURN 0; END IF;
  RETURN CASE WHEN t IS JSON THEN 1 ELSE 0 END;
END $func$;
CREATE OR REPLACE FUNCTION json_array_length(t text) RETURNS integer
LANGUAGE plpgsql IMMUTABLE AS $func$
BEGIN
  IF t IS NULL OR NOT (t IS JSON) THEN RETURN 0; END IF;
  RETURN json_array_length(t::json);
EXCEPTION WHEN OTHERS THEN RETURN 0;
END $func$;
CREATE OR REPLACE FUNCTION json_each(t text)
RETURNS TABLE(value text)
LANGUAGE plpgsql IMMUTABLE AS $func$
BEGIN
  IF t IS NULL OR NOT (t IS JSON) THEN RETURN; END IF;
  RETURN QUERY SELECT elem FROM json_array_elements_text(t::json) AS elem;
EXCEPTION WHEN OTHERS THEN RETURN;
END $func$;
"""


def bootstrap(*, dsn: str, apply: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="handraw-v3-schema-") as tmp:
        # Only a brand-new scratch DB; never materialize existing user data.
        scratch = Database(Path(tmp) / "empty_schema.sqlite3")
        try:
            migrations = scratch.migrate()
            conn = scratch.get_conn()
            tables = [
                row["name"] for row in conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                )
            ]
            columns, foreign_keys, indexes, identity = staging.inspect_schema(
                conn, tables, allow_omitting_nonunique_expressions=True,
            )
            required = {
                "generation_runs", "generation_items", "media_assets",
                "work_media", "works", "studio_generations", "users",
                "schema_migrations",
            }
            if not required.issubset(set(tables)):
                raise RuntimeError("Fresh V3 schema is missing its essential tables")
            report = {
                "ok": True, "mode": "fresh-v3-schema",
                "tables": len(tables), "foreignKeys": len(foreign_keys),
                "indexes": len(indexes), "migrationVersions": len(migrations),
                "dryRun": not apply, "userDataTransferred": False,
                "destructiveOperations": False,
            }
            if not apply:
                return report
            if os.environ.get("HANDRAW_ALLOW_PG_BOOTSTRAP") != "YES":
                raise RuntimeError("Set HANDRAW_ALLOW_PG_BOOTSTRAP=YES to initialize an empty PostgreSQL database")
            if not dsn:
                raise RuntimeError("HANDRAW_DATABASE_URL must point to an empty PostgreSQL database")
            if staging.psycopg is None:
                raise RuntimeError("Install psycopg[binary] to initialize PostgreSQL")

            from psycopg.conninfo import conninfo_to_dict
            parsed = conninfo_to_dict(dsn)
            if parsed.get("dbname") in ("postgres", "template0", "template1", ""):
                raise RuntimeError("Refusing to initialize a default/system PostgreSQL database")
            with staging.psycopg.connect(dsn, autocommit=False, connect_timeout=5) as pg:
                with pg.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM information_schema.tables
                        WHERE table_schema='public' AND table_type='BASE TABLE'
                        """
                    )
                    if int(cur.fetchone()[0]) != 0:
                        raise RuntimeError("Target is not empty: refusing to overwrite or merge any existing schema")
                    cur.execute("SET LOCAL lock_timeout='5s'")
                    cur.execute("SET LOCAL statement_timeout='120s'")
                    cur.execute("CREATE EXTENSION IF NOT EXISTS citext")
                    cur.execute(POSTGRES_JSON_HELPERS_SQL)
                    staging.build_tables(cur, conn, tables, columns, identity)
                    # Import only migration metadata. The source contains
                    # ZERO accounts, generated images or forum content.
                    for table in ("schema_migrations", "schema_migration_hooks"):
                        rows = conn.execute('SELECT * FROM "' + table + '"').fetchall()
                        if rows:
                            staging.import_rows(cur, conn, [table], columns)
                    staging.create_unique_indexes(cur, indexes)
                    staging.create_foreign_keys(cur, foreign_keys)
                    cur.execute(NATIVE_V3_SQL)
                    # PostgreSQL CHECK/trigger rules are intentionally stronger
                    # than a raw SQLite schema conversion.
                    for table in required:
                        cur.execute("SELECT to_regclass(%s)", ("public." + table,))
                        if cur.fetchone()[0] is None:
                            raise RuntimeError("Missing PostgreSQL V3 table " + table)
                pg.commit()
            report["dryRun"] = False
            report["created"] = True
            return report
        finally:
            scratch.close()


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
