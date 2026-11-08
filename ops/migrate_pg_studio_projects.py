#!/usr/bin/env python3
"""Non-destructive PostgreSQL migration 101 for existing Handraw V3 databases.

Unlike bootstrap_postgres_v3 this MUST run against a database containing users
and works. This tool adds *only* the Studio2 private project tables; it never
copies, drops or rewrites any existing table or content.

Dry-run:
  HANDRAW_DATABASE_URL=postgresql://... python -m ops.migrate_pg_studio_projects

Apply, after a database backup and a reviewed dry-run:
  HANDRAW_ALLOW_PG_STUDIO_MIGRATION=YES HANDRAW_DATABASE_URL=postgresql://... \
    python -m ops.migrate_pg_studio_projects --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

VERSION = 101
NAME = "101_studio_project_drafts"
ALLOW_ENV = "HANDRAW_ALLOW_PG_STUDIO_MIGRATION"
# Kept identical to the fresh PostgreSQL bootstrap's converted schema
# except that the index uses the original DESC ordering.
PROJECT_TABLES_SQL = """
CREATE TABLE public.studio_projects (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id),
    kind TEXT NOT NULL CHECK (kind IN ('image','series','article')),
    title TEXT NOT NULL DEFAULT '',
    authority TEXT NOT NULL CHECK (authority IN ('spec','graph','article')),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    draft_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX pg_idx_studio_projects_owner_updated
    ON public.studio_projects(user_id, updated_at DESC, id DESC);
CREATE TABLE public.studio_project_requests (
    user_id BIGINT NOT NULL REFERENCES public.users(id),
    project_id TEXT NOT NULL REFERENCES public.studio_projects(id),
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, project_id, idempotency_key)
);
"""
# An exclusive advisory lock only coordinates schema installers; normal writes
# are unaffected except for PostgreSQL's brief CREATE TABLE catalog locks.
LOCK_KEY = 729_032_101


def validate_database_name(dsn: str) -> None:
    # Safety checks must run even on build agents without psycopg installed.
    # The actual migration still requires psycopg, imported inside migrate().
    if not dsn:
        raise RuntimeError("HANDRAW_DATABASE_URL 未配置")
    try:
        parsed = urlsplit(dsn)
        database = unquote(parsed.path.lstrip("/"))
        if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname:
            raise ValueError("invalid PostgreSQL URL")
    except (ValueError, TypeError) as exc:
        raise RuntimeError("必须提供完整的 postgresql://host/database URL") from exc
    if not database or "/" in database or database.lower() in ("postgres", "template0", "template1"):
        raise RuntimeError("拒绝操作默认 PostgreSQL 系统数据库")
    # libpq permits query parameters overriding the URI's database/host.
    # Never inspect one target and write into another on --apply.
    overrides = {"dbname", "host", "hostaddr", "service", "servicefile", "options"}
    if any(key.lower() in overrides for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise RuntimeError("迁移地址禁止通过 query 参数覆盖数据库、主机或服务配置")


def inspect_state(cur: Any) -> dict[str, Any]:
    cur.execute("""SELECT
          to_regclass('public.schema_migrations'),
          to_regclass('public.users'),
          to_regclass('public.generation_runs'),
          to_regclass('public.media_assets'),
          to_regclass('public.studio_projects'),
          to_regclass('public.studio_project_requests'),
          to_regclass('public.pg_idx_studio_projects_owner_updated')""")
    tables = cur.fetchone()
    if not all(tables[:4]):
        raise RuntimeError("不是已初始化的 Handraw V3 数据库；拒绝自动 bootstrap")
    cur.execute("SELECT version,name FROM public.schema_migrations WHERE version IN (100,101)")
    found = {int(row[0]): str(row[1]) for row in cur.fetchall()}
    if 100 not in found:
        raise RuntimeError("缺少 native V3 migration 100；先执行现有 V3 预检")
    already = VERSION in found
    installed = [bool(value) for value in tables[4:]]
    if already:
        if found[VERSION] != NAME or not all(installed):
            raise RuntimeError("migration 101 标记存在但表/索引不完整；请人工审计")
        return {"alreadyApplied": True, "requiresMigration": False}
    if any(installed):
        raise RuntimeError("检测到未登记的 Studio Project 表/索引；拒绝在部分升级上继续")
    return {"alreadyApplied": False, "requiresMigration": True}


def migrate(*, dsn: str, apply: bool = False) -> dict[str, Any]:
    validate_database_name(dsn)
    # Import only when an actual DB operation is requested; pure tests may
    # import constants and inspect_state without PostgreSQL installed.
    import psycopg

    with psycopg.connect(dsn, autocommit=False, connect_timeout=5) as pg:
        with pg.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            state = inspect_state(cur)
            report: dict[str, Any] = {
                "ok": True, "migration": VERSION, "name": NAME,
                **state, "dryRun": not apply, "destructiveOperations": False,
                "userDataTransferred": False
            }
            if not state["requiresMigration"]:
                return report
            if not apply:
                return report
            if os.environ.get(ALLOW_ENV) != "YES":
                raise RuntimeError(f"必须设置 {ALLOW_ENV}=YES 才能执行正式迁移")
            # PG transactional DDL: failure rolls back both tables/index and
            # the version receipt atomically. No IF NOT EXISTS hides drift.
            cur.execute(PROJECT_TABLES_SQL)
            cur.execute(
                """INSERT INTO public.schema_migrations (version,name,applied_at)
                   VALUES (%s,%s,%s)""",
                (VERSION, NAME, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            if not inspect_state(cur)["alreadyApplied"]:
                raise RuntimeError("migration 101 验证失败，回滚升级")
            report.update({"dryRun": False, "applied": True, "alreadyApplied": True,
                           "requiresMigration": False})
            return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely add Studio2 Project tables to an EXISTING PostgreSQL V3 DB")
    parser.add_argument("--apply", action="store_true", help="执行事务型迁移（需要环境变量双重授权）")
    args = parser.parse_args(argv)
    try:
        result = migrate(dsn=os.environ.get("HANDRAW_DATABASE_URL", ""), apply=args.apply)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
