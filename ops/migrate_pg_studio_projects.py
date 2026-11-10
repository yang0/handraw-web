#!/usr/bin/env python3
"""Non-destructive PostgreSQL migrations 101-103 for existing Handraw V3 DBs.

Unlike bootstrap_postgres_v3 this MUST run against a database containing users
and works. This tool adds *only* additive Studio2 / owned-resource objects; it
never copies, drops or rewrites any existing table or content.

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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

VERSION = 101
NAME = "101_studio_project_drafts"
ALLOW_ENV = "HANDRAW_ALLOW_PG_STUDIO_MIGRATION"

# 101: Studio2 private project drafts. Kept identical to the fresh PostgreSQL
# bootstrap's converted schema except that the index uses DESC ordering.
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

# 102: review receipts for GraphPatch proposals (#126). Additive only.
GRAPH_PATCH_REVIEWS_SQL = """
CREATE TABLE public.studio_graphpatch_reviews (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id),
    project_id TEXT NOT NULL REFERENCES public.studio_projects(id),
    base_revision BIGINT NOT NULL,
    graph_revision BIGINT NOT NULL,
    before_graph_json TEXT NOT NULL,
    operations_json TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','applied','reverted')),
    applied_revision BIGINT,
    response_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX pg_idx_studio_graphpatch_owner
    ON public.studio_graphpatch_reviews(user_id, project_id, created_at);
"""

# 103: derived READ MODEL of skill_personal_resources (#21). The Skill CAS
# table remains the only authority; rows here are projected from it.
USER_RESOURCES_SQL = """
CREATE TABLE public.user_resources (
    id TEXT PRIMARY KEY REFERENCES public.skill_personal_resources(id),
    code TEXT NOT NULL UNIQUE,
    owner_user_id BIGINT NOT NULL REFERENCES public.users(id),
    kind TEXT NOT NULL CHECK (kind IN ('style','layout')),
    name TEXT NOT NULL,
    definition TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    revision BIGINT NOT NULL DEFAULT 1,
    deleted_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX pg_idx_user_resources_owner
    ON public.user_resources(owner_user_id, kind, deleted_at, updated_at);
INSERT INTO public.user_resources
    (id, code, owner_user_id, kind, name, definition, description, cover_url,
     revision, deleted_at, updated_at)
SELECT s.id,
       (CASE s.kind WHEN 'style' THEN 'USR-S' ELSE 'USR-L' END) ||
           UPPER(REPLACE(s.id, '-', '')),
       s.user_id, s.kind, s.name,
       COALESCE(
           CASE WHEN s.definition_json IS JSON
                THEN s.definition_json::json ->> 'zh' END, ''),
       '', '', s.revision, s.deleted_at, s.updated_at
FROM public.skill_personal_resources s
ON CONFLICT (id) DO NOTHING;
"""

# An exclusive advisory lock only coordinates schema installers; normal writes
# are unaffected except for PostgreSQL's brief CREATE TABLE catalog locks.
LOCK_KEY = 729_032_101


@dataclass(frozen=True)
class Step:
    version: int
    name: str
    ddl: str
    # Every object the receipt claims to have installed. A receipt without all
    # of them is drift and must be audited, never silently repaired.
    object_sql: str

    def inspect(self, cur: Any) -> tuple[bool, bool]:
        """Return (all installed, any installed).

        "Any installed without a receipt" is a partial upgrade and must never
        be repaired silently by re-running CREATE TABLE.
        """
        cur.execute(self.object_sql)
        found = [bool(value) for value in cur.fetchone()]
        return all(found), any(found)


STEPS = (
    Step(
        VERSION, NAME, PROJECT_TABLES_SQL,
        """SELECT to_regclass('public.studio_projects'),
                  to_regclass('public.studio_project_requests'),
                  to_regclass('public.pg_idx_studio_projects_owner_updated')""",
    ),
    Step(
        102, "102_studio_graphpatch_reviews", GRAPH_PATCH_REVIEWS_SQL,
        """SELECT to_regclass('public.studio_graphpatch_reviews'),
                  to_regclass('public.pg_idx_studio_graphpatch_owner')""",
    ),
    Step(
        103, "103_author_private_resource_projection", USER_RESOURCES_SQL,
        """SELECT to_regclass('public.user_resources'),
                  to_regclass('public.pg_idx_user_resources_owner')""",
    ),
)


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
    # 103 derives its rows from the Skill authority table, so that table (and
    # the two V3 baselines this tool depends on) must already exist.
    cur.execute("""SELECT
          to_regclass('public.schema_migrations'),
          to_regclass('public.users'),
          to_regclass('public.generation_runs'),
          to_regclass('public.media_assets')""")
    if not all(cur.fetchone()):
        raise RuntimeError("不是已初始化的 Handraw V3 数据库；拒绝自动 bootstrap")
    cur.execute("""
        SELECT to_regclass('public.skill_personal_resources'),
               to_regclass('public.skill_resource_changes')""")
    skill_tables = [bool(value) for value in cur.fetchone()]

    versions = [step.version for step in STEPS]
    cur.execute(
        "SELECT version,name FROM public.schema_migrations WHERE version = ANY(%s)",
        ([100, *versions],),
    )
    found = {int(row[0]): str(row[1]) for row in cur.fetchall()}
    if 100 not in found:
        raise RuntimeError("缺少 native V3 migration 100；先执行现有 V3 预检")

    steps: list[dict[str, Any]] = []
    for step in STEPS:
        complete, any_present = step.inspect(cur)
        registered = found.get(step.version)
        if registered is not None:
            if registered != step.name or not complete:
                raise RuntimeError(
                    f"migration {step.version} 标记存在但表/索引不完整；请人工审计"
                )
            state = "applied"
        elif any_present:
            raise RuntimeError(
                f"检测到未登记的 {step.name} 表/索引；拒绝在部分升级上继续"
            )
        elif step.version == 103 and not all(skill_tables):
            raise RuntimeError(
                "migration 103 依赖 skill_personal_resources / skill_resource_changes；"
                "缺少 Skill 权威表，拒绝创建空投影"
            )
        else:
            state = "pending"
        steps.append({"version": step.version, "name": step.name, "state": state})

    pending = [step["version"] for step in steps if step["state"] == "pending"]
    return {
        "steps": steps,
        "alreadyApplied": not pending,
        "requiresMigration": bool(pending),
        "pendingVersions": pending,
    }


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
            applied: list[int] = []
            # PG transactional DDL: failure rolls back every table/index and
            # receipt together. No IF NOT EXISTS hides drift.
            for step in STEPS:
                if step.version not in state["pendingVersions"]:
                    continue
                cur.execute(step.ddl)
                cur.execute(
                    """INSERT INTO public.schema_migrations (version,name,applied_at)
                       VALUES (%s,%s,%s)""",
                    (step.version, step.name,
                     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                )
                if not step.inspect(cur)[0]:
                    raise RuntimeError(
                        f"migration {step.version} 验证失败，回滚升级"
                    )
                applied.append(step.version)
            final = inspect_state(cur)
            if final["requiresMigration"]:
                raise RuntimeError("migration 验证失败，回滚升级")
            report.update({"dryRun": False, "applied": True, "appliedVersions": applied,
                           "alreadyApplied": True, "requiresMigration": False,
                           "pendingVersions": []})
            return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely add Studio2 / owned-resource objects to an EXISTING PostgreSQL V3 DB")
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
