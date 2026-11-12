#!/usr/bin/env python3
"""Back up Handraw PostgreSQL and local media, or restore into isolated targets."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 2
DATABASE_ARCHIVE = "database.dump"
BACKUP_PREFIX = "handraw-pg"

if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT))

from ops.postgres_backup import PostgresArchiveError, inspect_pg_archive, restore_pg_archive, write_pg_archive


class OperationsError(RuntimeError):
    """A safe, user-actionable operation failure."""


class SafetyError(OperationsError):
    """The requested operation would overwrite an existing target."""


class BackupIntegrityError(OperationsError):
    """The archive or its manifest failed verification."""


@dataclass(frozen=True)
class Workspace:
    root: Path
    database_url: str = field(repr=False)
    uploads: Path
    generated: Path

    @classmethod
    def resolve(
        cls,
        root: Path | str | None = None,
        database_url: str | None = None,
        uploads: Path | str | None = None,
        generated: Path | str | None = None,
    ) -> "Workspace":
        root_path = _absolute_directory(root or os.environ.get("HANDRAW_WEB_ROOT") or REPO_ROOT)
        storage = Path(os.environ.get("HANDRAW_PRIVATE_STORAGE") or (root_path / ".local")).expanduser()
        uploads_path = _absolute_directory(uploads or os.environ.get("HANDRAW_UPLOADS_DIR") or storage / "uploads")
        generated_path = _absolute_directory(generated or os.environ.get("HANDRAW_GENERATED_DIR") or storage / "demo_generated")
        if _overlap(uploads_path, generated_path):
            raise SafetyError("uploads 与 generated 目录不能重叠")
        dsn = (database_url if database_url is not None else os.environ.get("HANDRAW_DATABASE_URL", "")).strip()
        return cls(root_path, dsn, uploads_path, generated_path)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _absolute_directory(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise SafetyError(f"目录不能是符号链接：{candidate}")
    result = candidate.resolve()
    if result == Path(result.anchor):
        raise SafetyError("目录不能指向文件系统根目录")
    return result


def _overlap(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def _remove_reserved_directory(path: Path, identity: os.stat_result) -> None:
    # The caller reserved this exact destination with an exclusive mkdir.
    try:
        current = path.lstat()
    except FileNotFoundError:
        return
    if path.is_symlink() or path.resolve() != path or not os.path.samestat(identity, current):
        raise SafetyError(f"暂存目录已变化，拒绝清理：{path}")
    shutil.rmtree(path)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_fingerprint(path: Path) -> str:
    return _digest(os.path.normcase(path.as_posix()))


def _database_fingerprint(dsn: str) -> str:
    if not dsn:
        raise OperationsError("请设置 HANDRAW_DATABASE_URL")
    from psycopg.conninfo import conninfo_to_dict

    settings = conninfo_to_dict(dsn)
    if settings.get("dbname") in (None, "", "postgres", "template0", "template1"):
        raise SafetyError("连接必须明确指定业务数据库")
    address = {
        key: settings.get(key, os.environ.get(env, default))
        for key, env, default in (
            ("host", "PGHOST", ""), ("hostaddr", "PGHOSTADDR", ""), ("port", "PGPORT", "5432"),
            ("service", "PGSERVICE", ""),
        )
    }
    return _digest(json.dumps({**address, "dbname": settings["dbname"]}, sort_keys=True))


def _manifest_targets(workspace: Workspace) -> dict[str, str]:
    return {
        "database": _database_fingerprint(workspace.database_url),
        "uploads": _path_fingerprint(workspace.uploads),
        "generated": _path_fingerprint(workspace.generated),
    }


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _iter_files(directory: Path) -> Iterable[tuple[str, Path]]:
    if not directory.exists():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise SafetyError(f"私有目录无效：{directory}")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise SafetyError(f"私有文件路径越界或为符号链接：{path}")
        if path.is_file():
            yield path.relative_to(directory).as_posix(), path


def _file_inventory(directory: Path) -> list[dict[str, Any]]:
    return [
        {"path": name, "size": path.stat().st_size, "sha256": _sha256_file(path)}
        for name, path in _iter_files(directory)
    ]


def _copy_private_tree(source: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    for relative, path in _iter_files(source):
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o600)


def _schema_migrations(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT version, name, applied_at FROM public.schema_migrations ORDER BY version")
    return [{"version": version, "name": name, "appliedAt": applied} for version, name, applied in rows]


def _read_manifest(backup: Path) -> dict[str, Any]:
    path = backup / MANIFEST_NAME
    if path.is_symlink() or not path.is_file():
        raise BackupIntegrityError("备份缺少有效 manifest")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise BackupIntegrityError("manifest 不是有效 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("formatVersion") != MANIFEST_VERSION:
        raise BackupIntegrityError("不支持的备份 manifest 版本")
    if not isinstance(manifest.get("targets"), dict) or not manifest.get("workspaceId"):
        raise BackupIntegrityError("manifest 缺少源工作区信息")
    return manifest


def _backup_summary(backup: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "backup": str(backup),
        "workspaceId": manifest["workspaceId"],
        "database": {"format": "postgresql-custom", "sha256": manifest["database"]["sha256"]},
        "uploads": len(manifest["privateFiles"]["uploads"]),
        "generated": len(manifest["privateFiles"]["generated"]),
        "schemaMigrations": manifest["database"]["schemaMigrations"],
    }


def _verify_backup(backup: Path, workspace: Workspace | None) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _read_manifest(backup)
    if workspace is not None and (
        manifest["workspaceId"] != _path_fingerprint(workspace.root)
        or manifest["targets"] != _manifest_targets(workspace)
    ):
        raise SafetyError("备份来源与当前工作区配置不一致")

    database = manifest.get("database")
    archive = backup / DATABASE_ARCHIVE
    if (not isinstance(database, dict) or database.get("file") != DATABASE_ARCHIVE
            or not archive.is_file() or archive.is_symlink()):
        raise BackupIntegrityError("PostgreSQL 归档路径无效")
    archive_hash = _sha256_file(archive)
    if archive_hash != database.get("sha256"):
        raise BackupIntegrityError("PostgreSQL 归档 checksum 不匹配")
    migrations = database.get("schemaMigrations")
    if (not isinstance(migrations, list) or not all(isinstance(row, dict) for row in migrations)
            or not any(row.get("version") == 100 for row in migrations)):
        raise BackupIntegrityError("归档缺少 Handraw V3 迁移记录")
    try:
        inspect_pg_archive(archive)
    except PostgresArchiveError as exc:
        raise BackupIntegrityError(str(exc)) from exc

    files = manifest.get("privateFiles")
    if not isinstance(files, dict):
        raise BackupIntegrityError("manifest 缺少私有文件清单")
    for label in ("uploads", "generated"):
        subtree = backup / label
        if not subtree.is_dir() or subtree.is_symlink() or _file_inventory(subtree) != files.get(label):
            raise BackupIntegrityError(f"{label} 文件清单或 checksum 不匹配")
    return manifest, _backup_summary(backup, manifest)


def verify_backup(backup_dir: Path | str, workspace: Workspace | None = None) -> dict[str, Any]:
    return _verify_backup(_absolute_directory(backup_dir), workspace)[1]


def backup_workspace(workspace: Workspace, destination: Path | str) -> dict[str, Any]:
    import psycopg

    target = _absolute_directory(destination)
    if any(_overlap(target, path) for path in (workspace.uploads, workspace.generated)):
        raise SafetyError("备份目录不能与私有媒体目录重叠")
    targets = _manifest_targets(workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise SafetyError(f"备份目标已存在：{target}") from exc
    identity = target.stat()
    try:
        archive = target / DATABASE_ARCHIVE
        with psycopg.connect(workspace.database_url, connect_timeout=5) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
            migrations = _schema_migrations(conn)
            if not any(row["version"] == 100 for row in migrations):
                raise BackupIntegrityError("数据库缺少 Handraw V3 迁移记录")
            write_pg_archive(workspace.database_url, snapshot, archive)
        inspect_pg_archive(archive)
        _copy_private_tree(workspace.uploads, target / "uploads")
        _copy_private_tree(workspace.generated, target / "generated")
        manifest = {
            "formatVersion": MANIFEST_VERSION,
            "createdAtUtc": utc_now(),
            "workspaceId": _path_fingerprint(workspace.root),
            "targets": targets,
            "database": {
                "file": DATABASE_ARCHIVE, "sha256": _sha256_file(archive), "schemaMigrations": migrations,
            },
            "privateFiles": {label: _file_inventory(target / label) for label in ("uploads", "generated")},
        }
        pending = target / ".manifest.json"
        pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending.chmod(0o600)
        pending.rename(target / MANIFEST_NAME)
        return _backup_summary(target, manifest)
    except BaseException:
        _remove_reserved_directory(target, identity)
        raise


def _require_empty_restore_database(conn) -> None:
    occupied = conn.execute("""
        SELECT EXISTS (
            SELECT FROM pg_catalog.pg_namespace
            WHERE nspname NOT IN ('public', 'information_schema') AND nspname !~ '^pg_'
            UNION ALL
            SELECT FROM pg_catalog.pg_class WHERE relnamespace = 'public'::regnamespace
            UNION ALL
            SELECT FROM pg_catalog.pg_proc WHERE pronamespace = 'public'::regnamespace
            UNION ALL
            SELECT FROM pg_catalog.pg_type WHERE typnamespace = 'public'::regnamespace
            UNION ALL
            SELECT FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'
        )
    """).fetchone()[0]
    if occupied:
        raise SafetyError("恢复目标 PostgreSQL 库必须为空")


def restore_workspace(
    workspace: Workspace,
    backup_dir: Path | str,
    *,
    restore_database_url: str,
    restore_dir: Path | str,
    dry_run: bool = False,
) -> dict[str, Any]:
    import psycopg

    backup = _absolute_directory(backup_dir)
    destination = _absolute_directory(restore_dir)
    if destination.exists() or workspace.root.is_relative_to(destination) or any(
        _overlap(destination, path) for path in (backup, workspace.uploads, workspace.generated)
    ):
        raise SafetyError("恢复必须使用全新目录，且不能与源工作区、备份或私有媒体重叠")
    destination_fingerprint = _database_fingerprint(restore_database_url)
    if workspace.database_url and destination_fingerprint == _database_fingerprint(workspace.database_url):
        raise SafetyError("恢复目标必须是独立 PostgreSQL 库")

    manifest, summary = _verify_backup(backup, workspace if workspace.database_url else None)
    with psycopg.connect(restore_database_url, connect_timeout=5, autocommit=True) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(186, 190)").fetchone()[0]:
            raise SafetyError("该目标库已有恢复任务")
        _require_empty_restore_database(conn)
        if dry_run:
            return {**summary, "preflight": "ok", "dryRun": True}

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir(mode=0o700)
        identity = destination.stat()
        try:
            for label, restored_name in (("uploads", "uploads"), ("generated", "demo_generated")):
                restored = destination / restored_name
                _copy_private_tree(backup / label, restored)
                if _file_inventory(restored) != manifest["privateFiles"][label]:
                    raise BackupIntegrityError(f"恢复后的 {label} checksum 不匹配")
            restore_pg_archive(restore_database_url, backup / DATABASE_ARCHIVE)
        except BaseException:
            _remove_reserved_directory(destination, identity)
            raise

        if _schema_migrations(conn) != summary["schemaMigrations"]:
            raise BackupIntegrityError("隔离目标的迁移记录与归档清单不一致，未通过恢复验收")

    return {**summary, "restored": True, "storageRoot": str(destination)}


def health_status(url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Read a minimal health payload and discard any unexpected response data."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OperationsError("health URL 必须是 http(s) 地址")
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read(512 * 1024)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": int(exc.code), "error": "health endpoint 返回错误"}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"ok": False, "status": 0, "error": "health endpoint 无法访问"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "status": status, "error": "health endpoint 返回格式无效"}
    if not isinstance(payload, dict):
        return {"ok": False, "status": status, "error": "health endpoint 返回格式无效"}
    return {
        "ok": bool(payload.get("ok")) and status == 200,
        "status": status,
        "version": str(payload.get("version") or "")[:80],
        "db": bool(payload.get("db")),
    }


def _validate_admin_input(username: str, email: str, password: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{2,47}", username):
        raise OperationsError("admin username 需为 3-48 位安全字符")
    if email and (len(email) > 254 or "@" not in email):
        raise OperationsError("email 格式无效")
    if len(password) < 12 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise OperationsError("admin 密码至少 12 位，且必须同时包含字母和数字")


def bootstrap_admin(
    workspace: Workspace, *, username: str, display_name: str, email: str, password: str,
) -> dict[str, Any]:
    import psycopg
    from backend.security import hash_password

    if os.environ.get("HANDRAW_DEMO_MODE", "").strip() == "1":
        raise SafetyError("演示库禁止创建真实 admin")
    username, display_name, email = username.strip(), display_name.strip()[:80], email.strip().lower()
    _validate_admin_input(username, email, password)
    _database_fingerprint(workspace.database_url)
    password_hash = hash_password(password)
    now = utc_now()
    with psycopg.connect(workspace.database_url, connect_timeout=5) as conn:
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SELECT pg_advisory_xact_lock(186, 191)")
        if not conn.execute("SELECT 1 FROM public.schema_migrations WHERE version=100").fetchone():
            raise OperationsError("请先初始化 Handraw V3 业务库")
        if conn.execute("SELECT 1 FROM public.users WHERE username=%s", (username,)).fetchone():
            raise OperationsError("该 username 已存在")
        if conn.execute("SELECT 1 FROM public.users WHERE role='admin' AND status='active'").fetchone():
            raise OperationsError("已有 active admin，拒绝重复 bootstrap")
        user_id = int(conn.execute(
            """
            INSERT INTO public.users(username, display_name, email, password_hash, role, status, invite_code, created_at)
            VALUES (%s, %s, %s, %s, 'admin', 'active', %s, %s) RETURNING id
            """,
            (username, display_name or username, email or None, password_hash, "admin-" + uuid.uuid4().hex, now),
        ).fetchone()[0])
        conn.execute("INSERT INTO public.wallets(user_id, balance, updated_at) VALUES (%s, 0, %s)", (user_id, now))
    return {"ok": True, "userId": user_id, "username": username, "role": "admin"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Handraw PostgreSQL 备份、隔离恢复和运维")
    parser.add_argument("--root", help="workspace 根目录")
    parser.add_argument("--uploads", help="私有 uploads 目录")
    parser.add_argument("--generated", help="私有 generated 目录")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="备份 PostgreSQL 快照与本地私有媒体")
    backup.add_argument("--output-dir", type=Path, required=True)
    verify = sub.add_parser("verify", help="核对原生归档及文件清单")
    verify.add_argument("--backup", type=Path, required=True)
    restore = sub.add_parser("restore", help="恢复到 HANDRAW_RESTORE_DATABASE_URL 指定的空库")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--restore-dir", type=Path, required=True, help="新建隔离媒体目录")
    restore.add_argument("--dry-run", action="store_true", help="只验证归档和恢复目标")
    health = sub.add_parser("health", help="读取最小健康状态")
    health.add_argument("--url", default="http://127.0.0.1:3080/api/health")
    admin = sub.add_parser("bootstrap-admin", help="创建首个真实 admin")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", default="")
    admin.add_argument("--email", default="")
    admin.add_argument("--password-stdin", action="store_true", help="从 stdin 读取两行密码")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import psycopg

    try:
        if args.command == "health":
            result = health_status(args.url)
        else:
            workspace = Workspace.resolve(args.root, uploads=args.uploads, generated=args.generated)
            if args.command == "backup":
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                target = args.output_dir / f"{BACKUP_PREFIX}-{stamp}-{uuid.uuid4().hex[:8]}"
                result = backup_workspace(workspace, target)
            elif args.command == "verify":
                result = verify_backup(args.backup, workspace if workspace.database_url else None)
            elif args.command == "restore":
                restore_dsn = os.environ.get("HANDRAW_RESTORE_DATABASE_URL", "").strip()
                if not restore_dsn:
                    raise OperationsError("请设置 HANDRAW_RESTORE_DATABASE_URL")
                result = restore_workspace(
                    workspace, args.backup, restore_database_url=restore_dsn,
                    restore_dir=args.restore_dir, dry_run=args.dry_run,
                )
            else:
                if args.password_stdin:
                    password = sys.stdin.readline().rstrip("\r\n")
                    confirmation = sys.stdin.readline().rstrip("\r\n")
                else:
                    password = getpass.getpass("新 admin 密码（不会显示）：")
                    confirmation = getpass.getpass("再次输入密码（不会显示）：")
                if password != confirmation:
                    raise OperationsError("两次密码不一致")
                result = bootstrap_admin(
                    workspace, username=args.username, display_name=args.display_name,
                    email=args.email, password=password,
                )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except psycopg.Error as exc:
        # Driver diagnostics may include SQL values or connection parameters.
        message = f"PostgreSQL 操作失败（{exc.sqlstate or type(exc).__name__}）"
    except (OperationsError, PostgresArchiveError, OSError, ValueError) as exc:
        message = str(exc)[:300]
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
