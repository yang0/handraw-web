#!/usr/bin/env python3
"""#112 PostgreSQL backup -> isolated restore -> transactional rollback drill.

Safeguards:
- NEVER creates, drops or overwrites a database.
- Only restores to TWO separately pre-created, EMPTY databases whose names
  start with handraw_restore_drill_. Source is read-only.
- Requires HANDRAW_ALLOW_PG_RESTORE_DRILL=YES and explicit source/target DSNs.
- pg_dump custom archive, pg_restore --exit-on-error, SHA256 archive and
  all-row SHA256 fingerprints for key business tables. Reports contain NO PII.
- Optional Docker execution mode is for CI's postgres:17 service only. Production
  uses local pg_dump/pg_restore tools with least-privilege DB credentials.

This validates an *isolated restore rehearsal*, not a production rollout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from ops.migrate_pg_studio_projects import validate_database_name

ALLOW_ENV = "HANDRAW_ALLOW_PG_RESTORE_DRILL"
PREFIX = "handraw_restore_drill_"
FINGERPRINT_TABLES = (
    "schema_migrations", "users", "wallets", "ledgers",
    "generation_runs", "generation_items", "media_assets", "work_media",
    "works", "studio_generations", "studio_projects",
    "studio_project_requests",
)


def settings(dsn: str) -> dict[str, str]:
    validate_database_name(dsn)
    from psycopg.conninfo import conninfo_to_dict
    info = conninfo_to_dict(dsn)
    if not info.get("dbname") or not info.get("host"):
        raise RuntimeError("必须提供明确的数据库名和 host，不能使用 libpq 默认值")
    return info


def preflight(source: str, restore: str, rollback: str, archive: Path) -> None:
    if os.environ.get(ALLOW_ENV) != "YES":
        raise RuntimeError(f"拒绝执行：必须显式设置 {ALLOW_ENV}=YES")
    src, dst, undo = settings(source), settings(restore), settings(rollback)
    names = [src["dbname"], dst["dbname"], undo["dbname"]]
    if len(set(names)) != 3:
        raise RuntimeError("源库、恢复库和回滚库必须是三个不同的数据库")
    for target in (dst, undo):
        if not target["dbname"].startswith(PREFIX):
            raise RuntimeError("恢复目标必须使用 handraw_restore_drill_ 专用前缀")
        if target["host"] != src["host"] or str(target.get("port","5432")) != str(src.get("port","5432")):
            raise RuntimeError("恢复目标必须与源库同一实例，不允许跨集群误写")
    if not archive.parent.is_dir() or archive.exists() or archive.is_symlink():
        raise RuntimeError("归档目录必须存在且归档文件不得已存在/是符号链接")


def verify_empty(dsn: str) -> None:
    import psycopg
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as pg:
        with pg.cursor() as cur:
            cur.execute("""SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema='public' AND table_type='BASE TABLE'""")
            if int(cur.fetchone()[0]):
                raise RuntimeError("恢复目标不为空，拒绝执行任何 pg_restore")
            cur.execute("SELECT COUNT(*) FROM pg_extension WHERE extname='citext'")
            # Existing extensions are allowed; only *application tables* must be empty.


def fingerprint(dsn: str) -> dict[str, Any]:
    """Read-only key-table fingerprint. Never emit raw row values or secrets."""
    import psycopg
    hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as pg:
        for table in FINGERPRINT_TABLES:
            with pg.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", ("public." + table,))
                if cur.fetchone()[0] is None:
                    raise RuntimeError("缺少关键数据表：" + table)
            digest = hashlib.sha256()
            total = 0
            # A named cursor streams large tables instead of buffering all
            # users/media/ledger records in the migration coordinator.
            with pg.cursor(name="audit_" + table) as rows:
                rows.execute('SELECT row_to_json(t)::text FROM public."' + table +
                             '" t ORDER BY row_to_json(t)::text')
                for record in rows:
                    digest.update(record[0].encode("utf-8"))
                    digest.update(b"\n")
                    total += 1
            hashes[table] = digest.hexdigest()
            counts[table] = total
    return {"rowCounts": counts, "rowSha256": hashes}


def _tool_prefix(container_id: str) -> list[str]:
    if container_id:
        # GitHub Actions service-container-only path. -e NAME imports the
        # value from subprocess env, never prints its credentials as arguments.
        return ["docker", "exec", "-i", "-e", "PGHOST", "-e", "PGPORT",
                "-e", "PGUSER", "-e", "PGPASSWORD", container_id]
    return []


def run_pg_tool(binary: str, dsn: str, archive: Path, *,
                restore: bool = False, container_id: str = "") -> None:
    info = settings(dsn)
    env = os.environ.copy()
    env["PGHOST"] = info["host"]
    env["PGPORT"] = str(info.get("port") or "5432")
    env["PGUSER"] = info.get("user") or ""
    env["PGPASSWORD"] = info.get("password") or ""
    command = _tool_prefix(container_id) + [
        binary, "--no-owner", "--no-acl",
        "--dbname=" + info["dbname"],
    ]
    if restore:
        command += ["--exit-on-error"]
        with archive.open("rb") as stream:
            result = subprocess.run(command, stdin=stream, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, env=env, timeout=360)
    else:
        command += ["--format=custom"]
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb") as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.PIPE,
                                    env=env, timeout=360)
    if result.returncode:
        # Avoid surfacing raw command/DSN or server exception fields which may
        # contain credentials; failures remain actionable by phase and exit.
        raise RuntimeError(f"{binary} 执行失败 (exit={result.returncode})")


def rollback_transaction_probe(dsn: str) -> None:
    import psycopg
    with psycopg.connect(dsn, autocommit=False, connect_timeout=5) as pg:
        try:
            with pg.cursor() as cur:
                cur.execute("CREATE TABLE public.qa_rollback_probe_112 (id bigint PRIMARY KEY)")
                cur.execute("INSERT INTO public.qa_rollback_probe_112 VALUES (1)")
                raise RuntimeError("intentionally rollback release transaction")
        except RuntimeError as error:
            if str(error) != "intentionally rollback release transaction":
                raise
            pg.rollback()
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as pg:
        result = pg.execute(
            "SELECT to_regclass('public.qa_rollback_probe_112')").fetchone()[0]
        if result is not None:
            raise RuntimeError("PostgreSQL 事务回滚未撤销演练 DDL")


def run_drill(*, source: str, restore: str, rollback: str, archive: Path,
              container_id: str = "") -> dict[str, Any]:
    preflight(source, restore, rollback, archive)
    # Fail closed before writing even the local archive.
    verify_empty(restore)
    verify_empty(rollback)
    before = fingerprint(source)
    if before["rowCounts"]["users"] < 1:
        raise RuntimeError("源数据库没有用户样本：无法验证账户/钱包恢复")
    run_pg_tool("pg_dump", source, archive, container_id=container_id)
    if archive.stat().st_size < 512:
        raise RuntimeError("归档过小，备份异常")
    archive_sha = hashlib.sha256()
    with archive.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            archive_sha.update(block)

    run_pg_tool("pg_restore", restore, archive, restore=True, container_id=container_id)
    restored = fingerprint(restore)
    if before != restored:
        raise RuntimeError("恢复后关键业务表的数量或逐行 SHA256 不一致")
    rollback_transaction_probe(restore)
    if fingerprint(restore) != before:
        raise RuntimeError("模拟失败升级事务后数据已变化")

    # Backup-based rollback is a restore into a *second empty database*.
    # Never drop, --clean or overwrite the running source.
    run_pg_tool("pg_restore", rollback, archive, restore=True, container_id=container_id)
    rolled_back = fingerprint(rollback)
    if rolled_back != before:
        raise RuntimeError("回滚副本与原备份存在数据差异")
    return {
        "ok":True, "issue":112, "mode":"isolated-pg-dump-custom-restore-rollback",
        "productionVerified":False, "sourceUntouched":True,
        "restoredIntoEmptyDisposableDbs":True,
        "transactionalRollbackVerified":True,
        "backupBasedRollbackVerified":True,
        "archiveSha256":archive_sha.hexdigest(),
        "archiveBytes":archive.stat().st_size,
        "verifiedTables":list(FINGERPRINT_TABLES),
        "rowCounts":before["rowCounts"],
        "fingerprintsMatched":True,
        "destructiveOperationsOnSource":False,
    }


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",required=True)
    parser.add_argument("--report",required=True)
    args=parser.parse_args(argv)
    try:
        result=run_drill(
            source=os.environ.get("HANDRAW_PG_DRILL_SOURCE_URL",""),
            restore=os.environ.get("HANDRAW_PG_DRILL_RESTORE_URL",""),
            rollback=os.environ.get("HANDRAW_PG_DRILL_ROLLBACK_URL",""),
            archive=Path(args.archive),
            container_id=os.environ.get("HANDRAW_PG_DRILL_DOCKER_CONTAINER",""),
        )
        Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                                     encoding="utf-8")
        print(json.dumps({**result,"rowCounts":result["rowCounts"]},
                         ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
