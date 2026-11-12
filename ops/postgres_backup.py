"""Native PostgreSQL archives for maintenance commands."""
from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


class PostgresArchiveError(RuntimeError):
    """A required PostgreSQL archive command failed."""


def postgres_tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable and os.name == "nt":
        installed = Path(r"D:\PostgreSQL\pgsql\bin") / f"{name}.exe"
        if installed.is_file():
            executable = str(installed)
    if not executable:
        raise PostgresArchiveError(f"PostgreSQL client tool required: {name}")
    return executable


@contextmanager
def _client_connection(dsn: str):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    settings = conninfo_to_dict(dsn)
    env = os.environ.copy()
    password = settings.pop("password", None)
    if password is not None:
        env["PGPASSWORD"] = password
    if "sslpassword" not in settings:
        yield make_conninfo(**settings), env
        return

    # libpq accepts a key password through a private service file.
    if any("\n" in value or "\r" in value for value in settings.values()):
        raise PostgresArchiveError("Connection settings cannot be represented in a libpq service file")
    with TemporaryDirectory(prefix="handraw-pg-client-") as temp:
        service = Path(temp) / "pg_service.conf"
        service.write_text("[handraw_archive]\n" + "".join(f"{key}={value}\n" for key, value in settings.items()), encoding="utf-8")
        service.chmod(0o600)
        env["PGSERVICEFILE"] = str(service)
        yield "service=handraw_archive", env


def _run_pg_tool(name: str, arguments: list[str], *, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run([postgres_tool(name), *arguments], env=env, capture_output=True)
    if result.returncode:
        raise PostgresArchiveError(f"{name} failed (exit status {result.returncode})")
    return result.stdout


def write_pg_archive(dsn: str, snapshot: str, destination: Path) -> None:
    with _client_connection(dsn) as (connection, env):
        _run_pg_tool(
            "pg_dump",
            ["--no-password", "--format=custom", "--dbname", connection,
             "--snapshot", snapshot, "--file", str(destination)],
            env=env,
        )
    if destination.stat().st_size == 0:
        raise PostgresArchiveError("pg_dump produced an empty archive")
    destination.chmod(0o600)


def inspect_pg_archive(archive: Path) -> None:
    entries = _run_pg_tool("pg_restore", ["--list", str(archive)])
    if (b" TABLE public schema_migrations " not in entries
            or b" TABLE DATA public schema_migrations " not in entries):
        raise PostgresArchiveError("Archive is missing the Handraw schema migration table or its data")


def restore_pg_archive(dsn: str, archive: Path) -> None:
    with _client_connection(dsn) as (connection, env):
        _run_pg_tool(
            "pg_restore",
            ["--no-password", "--single-transaction", "--exit-on-error", "--no-owner",
             "--no-privileges", "--dbname", connection, str(archive)],
            env=env,
        )


def dump_snapshot(dsn: str, snapshot: str, directory: Path, *, prefix: str = "social-counters-before") -> Path:
    directory = directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"{prefix}-{stamp}-{uuid4().hex[:8]}.dump"
    with TemporaryDirectory(prefix="handraw-pg-backup-", dir=directory) as temp:
        staging = Path(temp) / "snapshot.dump"
        write_pg_archive(dsn, snapshot, staging)
        inspect_pg_archive(staging)
        staging.replace(destination)
    return destination
