#!/usr/bin/env python3
"""Safe local operations for the Handraw Web 2.0 SQLite service.

This tool deliberately stays local and explicit.  It can create a consistent
SQLite backup while the application is online, copy private uploads/generated
files, verify a backup manifest, and restore only after the operator confirms
that all writers have stopped.  It never starts/stops a service, deploys code,
or prints credentials.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
BACKUP_PREFIX = "handraw-v2"
CHUNK_SIZE = 1024 * 1024

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class OperationsError(RuntimeError):
    """Base class for safe, user-actionable operation failures."""


class SafetyError(OperationsError):
    """The requested operation would cross a safety boundary."""


class BackupIntegrityError(OperationsError):
    """A backup or restored target failed checksum/integrity validation."""


@dataclass(frozen=True)
class Workspace:
    """Resolved paths for one Handraw Web workspace.

    Paths may point at a private storage volume outside ``root``.  The
    manifest stores only path fingerprints, never absolute paths or env-file
    contents.
    """

    root: Path
    database: Path
    uploads: Path
    generated: Path

    @classmethod
    def resolve(
        cls,
        root: Path | str | None = None,
        database: Path | str | None = None,
        uploads: Path | str | None = None,
        generated: Path | str | None = None,
    ) -> "Workspace":
        root_path = Path(root or os.environ.get("HANDRAW_WEB_ROOT") or REPO_ROOT).expanduser().resolve()
        if root_path == Path(root_path.anchor):
            raise SafetyError("workspace root 不能是文件系统根目录")

        storage = Path(os.environ.get("HANDRAW_PRIVATE_STORAGE") or (root_path / ".local")).expanduser()
        db_path = Path(database or os.environ.get("HANDRAW_DB_PATH") or (storage / "handraw_v2.db"))
        uploads_path = Path(uploads or os.environ.get("HANDRAW_UPLOADS_DIR") or (storage / "uploads"))
        generated_path = Path(generated or os.environ.get("HANDRAW_GENERATED_DIR") or (storage / "demo_generated"))
        return cls(root_path, db_path.expanduser().resolve(), uploads_path.expanduser().resolve(), generated_path.expanduser().resolve())


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_fingerprint(path: Path) -> str:
    """Fingerprint a target path without recording it in the manifest."""
    normalized = str(path.resolve()).replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _workspace_id(root: Path) -> str:
    return _path_fingerprint(root)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _assert_not_unsafe_target(path: Path, label: str) -> None:
    if path == Path(path.anchor):
        raise SafetyError(f"{label} 不能指向文件系统根目录")
    if path.is_symlink():
        raise SafetyError(f"{label} 不能是符号链接：{path}")


def _safe_remove(path: Path) -> None:
    """Remove one exact internal staging path, never a computed broad root."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(directory: Path) -> Iterable[tuple[str, Path]]:
    if not directory.exists():
        return
    if directory.is_symlink():
        raise SafetyError(f"私有目录不能是符号链接：{directory}")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise SafetyError(f"私有目录包含符号链接，已拒绝备份：{path}")
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            if not relative or relative.startswith("../") or "/../" in relative:
                raise SafetyError(f"私有文件路径越界：{relative}")
            yield relative, path


def _file_inventory(directory: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for relative, path in _iter_files(directory):
        inventory.append({"path": relative, "size": path.stat().st_size, "sha256": _sha256_file(path)})
    return inventory


def _copy_private_tree(source: Path, destination: Path) -> None:
    _assert_not_unsafe_target(destination, "备份目标")
    destination.mkdir(parents=True, exist_ok=False)
    if not source.exists():
        return
    _assert_not_unsafe_target(source, "私有源目录")
    for relative, path in _iter_files(source):
        target = destination / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
    for directory in sorted((p for p in destination.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    try:
        destination.chmod(0o700)
    except OSError:
        pass


def _sqlite_integrity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BackupIntegrityError(f"SQLite 文件不存在：{path}")
    connection = sqlite3.connect(str(path), timeout=15.0)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(row[0] if row else "")
        if integrity.lower() != "ok":
            raise BackupIntegrityError(f"SQLite integrity_check 失败：{integrity[:200]}")
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            raise BackupIntegrityError("SQLite foreign_key_check 失败")
        return {"integrity": "ok", "foreignKeyCheck": "ok"}
    finally:
        connection.close()


def _schema_migrations(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    connection = sqlite3.connect(str(path), timeout=15.0)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return []
        return [
            {"version": int(row["version"]), "name": str(row["name"])}
            for row in connection.execute("SELECT version, name FROM schema_migrations ORDER BY version")
        ]
    finally:
        connection.close()


def _sqlite_backup(source: Path, destination: Path) -> dict[str, Any]:
    """Take an online-consistent SQLite snapshot using the backup API."""
    if not source.is_file():
        raise OperationsError(f"SQLite 源文件不存在：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source), timeout=30.0)
    destination_conn = sqlite3.connect(str(destination), timeout=30.0)
    try:
        source_conn.backup(destination_conn, pages=256, sleep=0.05)
        destination_conn.commit()
    finally:
        destination_conn.close()
        source_conn.close()
    return _sqlite_integrity(destination)


def _target_descriptor(root: Path, path: Path) -> dict[str, Any]:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = None
    return {"relative": relative, "fingerprint": _path_fingerprint(path)}


def _manifest_targets(workspace: Workspace) -> dict[str, dict[str, Any]]:
    return {
        "database": _target_descriptor(workspace.root, workspace.database),
        "uploads": _target_descriptor(workspace.root, workspace.uploads),
        "generated": _target_descriptor(workspace.root, workspace.generated),
    }


def _manifest_path(backup_dir: Path) -> Path:
    return backup_dir / MANIFEST_NAME


def _read_manifest(backup_dir: Path) -> dict[str, Any]:
    manifest_path = _manifest_path(backup_dir)
    if not manifest_path.is_file():
        raise BackupIntegrityError(f"备份缺少 manifest：{manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BackupIntegrityError("manifest 不是有效 JSON") from exc
    if not isinstance(manifest, dict) or int(manifest.get("formatVersion", 0)) != MANIFEST_VERSION:
        raise BackupIntegrityError("不支持的备份 manifest 版本")
    if manifest.get("workspaceId") is None or not isinstance(manifest.get("targets"), dict):
        raise BackupIntegrityError("manifest 缺少 workspace/targets 安全信息")
    return manifest


def _validate_manifest_targets(workspace: Workspace, manifest: dict[str, Any]) -> None:
    if manifest.get("workspaceId") != _workspace_id(workspace.root):
        raise SafetyError("备份与当前 workspace 不一致，拒绝恢复")
    expected = manifest.get("targets") or {}
    current = _manifest_targets(workspace)
    for name in ("database", "uploads", "generated"):
        target = expected.get(name)
        if not isinstance(target, dict) or target.get("fingerprint") != current[name]["fingerprint"]:
            raise SafetyError(f"{name} 恢复目标与备份不一致，拒绝恢复")


def _validate_inventory(directory: Path, expected: list[dict[str, Any]], label: str) -> None:
    actual = _file_inventory(directory)
    if actual != expected:
        raise BackupIntegrityError(f"{label} 文件清单或 checksum 不匹配")


def verify_backup(backup_dir: Path | str, workspace: Workspace | None = None) -> dict[str, Any]:
    """Verify manifest, SQLite integrity, checksums, and optional target scope."""
    backup = Path(backup_dir).expanduser().resolve()
    _assert_not_unsafe_target(backup, "备份目录")
    manifest = _read_manifest(backup)
    if workspace is not None:
        _validate_manifest_targets(workspace, manifest)

    database = backup / str((manifest.get("database") or {}).get("file") or "database.sqlite3")
    if database.parent != backup or not database.is_file():
        raise BackupIntegrityError("manifest 的数据库文件路径无效")
    database_entry = manifest.get("database") or {}
    expected_db_hash = str(database_entry.get("sha256") or "")
    actual_db_hash = _sha256_file(database)
    if not expected_db_hash or expected_db_hash != actual_db_hash:
        raise BackupIntegrityError("SQLite 备份 checksum 不匹配")
    integrity = _sqlite_integrity(database)

    private_files = manifest.get("privateFiles") or {}
    for label in ("uploads", "generated"):
        subtree = backup / label
        expected = private_files.get(label) or []
        if not isinstance(expected, list):
            raise BackupIntegrityError(f"manifest 的 {label} 清单无效")
        _validate_inventory(subtree, expected, label)

    return {
        "ok": True,
        "backup": str(backup),
        "workspaceId": manifest.get("workspaceId"),
        "database": {"sha256": actual_db_hash, **integrity},
        "uploads": len(private_files.get("uploads") or []),
        "generated": len(private_files.get("generated") or []),
        "schemaMigrations": manifest.get("database", {}).get("schemaMigrations") or [],
    }


def _backup_destination_is_safe(destination: Path, workspace: Workspace) -> None:
    _assert_not_unsafe_target(destination, "备份目录")
    for source, label in (
        (workspace.database, "数据库"),
        (workspace.uploads, "uploads"),
        (workspace.generated, "generated"),
    ):
        if destination == source or _is_within(destination, source):
            raise SafetyError(f"备份目录不能位于 {label} 内：{destination}")


def backup_workspace(workspace: Workspace, destination: Path | str) -> dict[str, Any]:
    """Create one immutable backup directory and return its safe summary."""
    destination_path = Path(destination).expanduser().resolve()
    _backup_destination_is_safe(destination_path, workspace)
    if destination_path.exists():
        raise OperationsError(f"备份目标已存在，拒绝覆盖：{destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.with_name(f".{destination_path.name}.tmp-{uuid.uuid4().hex}")
    _assert_not_unsafe_target(staging, "备份临时目录")
    try:
        staging.mkdir(parents=True)
        database_copy = staging / "database.sqlite3"
        integrity = _sqlite_backup(workspace.database, database_copy)
        uploads_copy = staging / "uploads"
        generated_copy = staging / "generated"
        _copy_private_tree(workspace.uploads, uploads_copy)
        _copy_private_tree(workspace.generated, generated_copy)
        manifest = {
            "formatVersion": MANIFEST_VERSION,
            "kind": "handraw-v2-private-workspace",
            "createdAtUtc": utc_now(),
            "workspaceId": _workspace_id(workspace.root),
            "targets": _manifest_targets(workspace),
            "database": {
                "file": "database.sqlite3",
                "sha256": _sha256_file(database_copy),
                **integrity,
                "schemaMigrations": _schema_migrations(database_copy),
            },
            "privateFiles": {
                "uploads": _file_inventory(uploads_copy),
                "generated": _file_inventory(generated_copy),
            },
            "notes": [
                "SQLite snapshot created with sqlite3 backup API.",
                "Manifest contains no credentials; backup database/private files remain sensitive.",
            ],
        }
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            manifest_path.chmod(0o600)
            staging.chmod(0o700)
        except OSError:
            pass
        os.replace(staging, destination_path)
    except Exception:
        _safe_remove(staging)
        raise
    return verify_backup(destination_path, workspace)


def _schema_version_set(path: Path) -> set[int]:
    return {int(item["version"]) for item in _schema_migrations(path)}


def _preflight_schema_restore(workspace: Workspace, backup_dir: Path, manifest: dict[str, Any]) -> None:
    current_versions = _schema_version_set(workspace.database)
    backup_versions = {int(item["version"]) for item in (manifest.get("database", {}).get("schemaMigrations") or [])}
    if current_versions and (not backup_versions or max(current_versions) > max(backup_versions)):
        raise SafetyError("备份数据库版本低于当前数据库，拒绝回滚数据库迁移")


def restore_preflight(workspace: Workspace, backup_dir: Path | str) -> dict[str, Any]:
    backup = Path(backup_dir).expanduser().resolve()
    _backup_destination_is_safe(backup, workspace)
    summary = verify_backup(backup, workspace)
    manifest = _read_manifest(backup)
    _preflight_schema_restore(workspace, backup, manifest)
    if backup == workspace.database or _is_within(backup, workspace.uploads) or _is_within(backup, workspace.generated):
        raise SafetyError("备份目录不能与恢复目标重叠")
    return {**summary, "preflight": "ok", "databaseDowngrade": False}


def _copy_tree_to_staging(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.copytree(source, destination, symlinks=False)
    else:
        destination.mkdir(parents=True)


def _restore_replace(
    workspace: Workspace,
    backup: Path,
    manifest: dict[str, Any],
) -> tuple[list[tuple[Path, Path | None]], Path | None]:
    """Swap exact files/dirs into place and retain old paths for rollback."""
    token = uuid.uuid4().hex
    old_paths: list[tuple[Path, Path | None]] = []
    db_old: Path | None = None
    db_stage = workspace.database.with_name(f".{workspace.database.name}.restore-new-{token}")
    db_old = workspace.database.with_name(f".{workspace.database.name}.restore-old-{token}")
    _assert_not_unsafe_target(db_stage, "数据库临时文件")
    _assert_not_unsafe_target(db_old, "数据库旧文件")
    shutil.copy2(backup / "database.sqlite3", db_stage)
    _sqlite_integrity(db_stage)
    workspace.database.parent.mkdir(parents=True, exist_ok=True)
    if workspace.database.exists():
        os.replace(workspace.database, db_old)
    os.replace(db_stage, workspace.database)

    for label, destination in (("uploads", workspace.uploads), ("generated", workspace.generated)):
        source = backup / label
        new_path = destination.with_name(f".{destination.name}.restore-new-{token}")
        old_path = destination.with_name(f".{destination.name}.restore-old-{token}")
        _assert_not_unsafe_target(new_path, f"{label} 临时目录")
        _assert_not_unsafe_target(old_path, f"{label} 旧目录")
        _copy_tree_to_staging(source, new_path)
        previous: Path | None = None
        if destination.exists():
            os.replace(destination, old_path)
            previous = old_path
        os.replace(new_path, destination)
        old_paths.append((destination, previous))

    # SQLite sidecars must not be allowed to attach to the restored database.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{workspace.database}{suffix}")
        if sidecar.exists():
            sidecar_old = Path(f"{sidecar}.restore-old-{token}")
            os.replace(sidecar, sidecar_old)
            old_paths.append((sidecar, sidecar_old))
    return old_paths, db_old


def _restore_rollback(workspace: Workspace, old_paths: list[tuple[Path, Path | None]], db_old: Path | None) -> None:
    for destination, previous in reversed(old_paths):
        _safe_remove(destination)
        if previous and previous.exists():
            os.replace(previous, destination)
    _safe_remove(workspace.database)
    if db_old and db_old.exists():
        os.replace(db_old, workspace.database)


def _cleanup_old_paths(old_paths: list[tuple[Path, Path | None]], db_old: Path | None) -> None:
    for _, previous in old_paths:
        if previous:
            _safe_remove(previous)
    if db_old:
        _safe_remove(db_old)


def _verify_restored_workspace(workspace: Workspace, manifest: dict[str, Any]) -> None:
    database_entry = manifest.get("database") or {}
    if _sha256_file(workspace.database) != database_entry.get("sha256"):
        raise BackupIntegrityError("恢复后的 SQLite checksum 不匹配")
    _sqlite_integrity(workspace.database)
    private_files = manifest.get("privateFiles") or {}
    _validate_inventory(workspace.uploads, private_files.get("uploads") or [], "恢复后的 uploads")
    _validate_inventory(workspace.generated, private_files.get("generated") or [], "恢复后的 generated")


def restore_workspace(
    workspace: Workspace,
    backup_dir: Path | str,
    *,
    stop_write: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Restore a verified backup after an explicit writer-stop assertion."""
    if not stop_write:
        raise SafetyError("恢复前必须显式确认 --stop-write；工具不会替你停止进程")
    preflight = restore_preflight(workspace, backup_dir)
    backup = Path(backup_dir).expanduser().resolve()
    if dry_run:
        return {**preflight, "dryRun": True}

    pre_restore = backup.parent / f"{BACKUP_PREFIX}-pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    current_backup = backup_workspace(workspace, pre_restore)
    manifest = _read_manifest(backup)
    old_paths: list[tuple[Path, Path | None]] = []
    db_old: Path | None = None
    try:
        old_paths, db_old = _restore_replace(workspace, backup, manifest)
        _verify_restored_workspace(workspace, manifest)
    except Exception:
        _restore_rollback(workspace, old_paths, db_old)
        raise
    _cleanup_old_paths(old_paths, db_old)
    return {**preflight, "restored": True, "preRestoreBackup": current_backup["backup"]}


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
    workspace: Workspace,
    *,
    username: str,
    display_name: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    """Create the first real admin without a default password or demo seed."""
    if os.environ.get("HANDRAW_DEMO_MODE", "").strip() == "1":
        raise SafetyError("HANDRAW_DEMO_MODE=1 时禁止创建真实 admin")
    username = username.strip()
    display_name = display_name.strip()[:80]
    email = email.strip().lower()
    _validate_admin_input(username, email, password)
    workspace.database.parent.mkdir(parents=True, exist_ok=True)

    # Import only here so the operations tool remains usable for backup/health
    # even when application dependencies are not installed.
    from backend.db import Database
    from backend.security import hash_password

    db = Database(workspace.database)
    db.migrate()
    now = utc_now()
    invite_code = f"admin-{uuid.uuid4().hex}"
    try:
        with db.transaction() as tx:
            if tx.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone():
                raise OperationsError("该 username 已存在")
            if tx.execute("SELECT 1 FROM users WHERE role = 'admin' AND status = 'active'").fetchone():
                raise OperationsError("已有 active admin，拒绝重复 bootstrap")
            cursor = tx.execute(
                """
                INSERT INTO users (
                    username, display_name, email, password_hash, password_algo,
                    role, status, bio, invite_code, created_at
                ) VALUES (?, ?, ?, ?, 'pbkdf2_sha256', 'admin', 'active', '', ?, ?)
                """,
                (username, display_name or username, email or None, hash_password(password), invite_code, now),
            )
            user_id = int(cursor.lastrowid)
            tx.execute(
                "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 0, '', 0, '', 0, ?)",
                (user_id, now),
            )
    finally:
        db.close()
    return {"ok": True, "userId": user_id, "username": username, "role": "admin"}


def _cli_workspace(args: argparse.Namespace) -> Workspace:
    return Workspace.resolve(args.root, args.db, args.uploads, args.generated)


def _new_backup_destination(parent: Path) -> Path:
    parent = parent.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    return parent / f"{BACKUP_PREFIX}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Handraw Web 2.0 本地备份、恢复、健康与首个 admin 工具")
    parser.add_argument("--root", default=str(REPO_ROOT), help="workspace 根目录")
    parser.add_argument("--db", default=None, help="SQLite 文件路径，默认读取 HANDRAW_DB_PATH 或 .local/handraw_v2.db")
    parser.add_argument("--uploads", default=None, help="私有 uploads 目录")
    parser.add_argument("--generated", default=None, help="私有 generated 目录")
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="在线一致备份 SQLite 与私有媒体")
    backup.add_argument("--output-dir", required=True, help="备份父目录；工具创建新的不可覆盖子目录")

    verify = sub.add_parser("verify", help="验证备份 manifest、checksum 与 SQLite integrity")
    verify.add_argument("--backup", required=True)

    restore = sub.add_parser("restore", help="预检并恢复备份；不会替你停止写入进程")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--stop-write", action="store_true", help="确认应用/worker/gateway 已停止写入")
    restore.add_argument("--dry-run", action="store_true", help="只做预检，不改变任何文件")

    health = sub.add_parser("health", help="读取最小健康状态，不打印响应中的敏感字段")
    health.add_argument("--url", default="http://127.0.0.1:3080/api/health")

    admin = sub.add_parser("bootstrap-admin", help="创建首个真实 admin，不生成默认密码")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", default="")
    admin.add_argument("--email", default="")
    admin.add_argument("--password-stdin", action="store_true", help="从 stdin 读取两行密码；不回显")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "health":
            print(json.dumps(health_status(args.url), ensure_ascii=False))
            return 0

        workspace = _cli_workspace(args)
        if args.command == "backup":
            destination = _new_backup_destination(Path(args.output_dir))
            print(json.dumps(backup_workspace(workspace, destination), ensure_ascii=False, indent=2))
            return 0
        if args.command == "verify":
            print(json.dumps(verify_backup(Path(args.backup), workspace), ensure_ascii=False, indent=2))
            return 0
        if args.command == "restore":
            print(
                json.dumps(
                    restore_workspace(workspace, Path(args.backup), stop_write=args.stop_write, dry_run=args.dry_run),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "bootstrap-admin":
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\r\n")
                confirmation = sys.stdin.readline().rstrip("\r\n")
            else:
                password = getpass.getpass("新 admin 密码（不会显示）：")
                confirmation = getpass.getpass("再次输入密码（不会显示）：")
            if password != confirmation:
                raise OperationsError("两次密码不一致")
            result = bootstrap_admin(
                workspace,
                username=args.username,
                display_name=args.display_name,
                email=args.email,
                password=password,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        parser.error("未知命令")
    except (OperationsError, sqlite3.Error, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
