"""Transactions and verified PostgreSQL snapshots for maintenance commands."""
from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from pathlib import Path

from backend.config import get_storage_root
from ops.postgres_backup import dump_snapshot


def maintenance_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--apply", action="store_true", help="Write after taking a verified snapshot (default: dry run)")
    parser.add_argument("--backup-dir", type=Path, default=get_storage_root() / "backups")
    return parser


@contextmanager
def maintenance_transaction(parser: argparse.ArgumentParser, *, write: bool):
    with maintenance_database(parser) as (db, dsn), db.transaction() as conn:
        configure_transaction(conn, write=write)
        yield conn, dsn


@contextmanager
def maintenance_database(parser: argparse.ArgumentParser):
    from backend.postgres_db import PostgresDatabase

    dsn = os.environ.get("HANDRAW_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("Set HANDRAW_DATABASE_URL to the target PostgreSQL database")
    db = PostgresDatabase(dsn)
    try:
        yield db, dsn
    finally:
        db.close()


def configure_transaction(conn, *, write: bool):
    if write:
        conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        conn.execute("SET LOCAL lock_timeout = '5s'")
        if not conn.execute("SELECT pg_try_advisory_xact_lock(186, 192)").fetchone()[0]:
            raise RuntimeError("Another data maintenance transaction is active")
    else:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")


def backup_before_change(conn, dsn: str, directory: Path, prefix: str) -> Path:
    snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
    return dump_snapshot(dsn, snapshot, directory, prefix=prefix)


@contextmanager
def savepoint(conn):
    conn.execute("SAVEPOINT maintenance_item")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT maintenance_item")
        raise
    finally:
        conn.execute("RELEASE SAVEPOINT maintenance_item")


def is_transaction_conflict(error: Exception) -> bool:
    return getattr(error, "sqlstate", None) in {"40001", "40P01", "55P03"}
