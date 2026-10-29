"""Thread-safe SQLite WAL database manager with additive migrations and ACID transactions."""
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from .config import get_db_path
from .migrations import MIGRATIONS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_MIGRATION_NAME_RE = re.compile(r"^[0-9]{3}_[a-z0-9_]+$")


def local_today_str() -> str:
    # Business-day quota and reservation accounting is defined in the
    # product's China timezone, not the machine timezone running the worker.
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


class Database:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_db_path()
        self._write_lock = threading.RLock()
        self._local = threading.local()
        self._all_conns: set[sqlite3.Connection] = set()
        self._conns_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=10000;")
        with self._conns_lock:
            self._all_conns.add(conn)
        return conn

    def get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None or getattr(self._local, "db_path", None) != str(self.db_path):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                with self._conns_lock:
                    self._all_conns.discard(conn)
            conn = self._connect()
            self._local.conn = conn
            self._local.db_path = str(self.db_path)
        return conn

    def close_thread_conn(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            with self._conns_lock:
                self._all_conns.discard(conn)
            self._local.conn = None

    def close(self) -> None:
        with self._conns_lock:
            conns = list(self._all_conns)
            self._all_conns.clear()
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        self._local.conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.get_conn()
            conn.execute("BEGIN IMMEDIATE;")
            try:
                yield conn
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def migrate(self) -> list[str]:
        applied_names: list[str] = []
        with self._write_lock:
            conn = self.get_conn()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                """
            )
            existing = {
                int(row["version"])
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            now = utc_now_iso()
            for version, name, ddl in MIGRATIONS:
                if version in existing:
                    continue
                if not isinstance(version, int) or not _MIGRATION_NAME_RE.fullmatch(name):
                    raise RuntimeError(f"invalid migration id: {version!r} {name!r}")
                # DDL and its bookkeeping must commit together.  ``executescript``
                # implicitly commits first, so a failure halfway through used to
                # leave an un-recorded partial migration behind -- and SQLite's
                # ``ALTER TABLE ADD COLUMN`` has no ``IF NOT EXISTS``, so the
                # re-run then failed permanently with "duplicate column name".
                script = (
                    "BEGIN IMMEDIATE;\n"
                    + ddl
                    + "\n;\n"
                    + "INSERT INTO schema_migrations (version, name, applied_at) VALUES ("
                    + str(version)
                    + ", '"
                    + name
                    + "', '"
                    + now
                    + "');\n"
                    + "COMMIT;"
                )
                try:
                    conn.executescript(script)
                except Exception:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK;")
                    raise
                applied_names.append(name)
        return applied_names


_DEFAULT_DB: Database | None = None
_DB_INIT_LOCK = threading.Lock()


def get_database(db_path: Path | str | None = None) -> Database:
    global _DEFAULT_DB
    target = Path(db_path).resolve() if db_path else get_db_path()
    with _DB_INIT_LOCK:
        if _DEFAULT_DB is None or _DEFAULT_DB.db_path.resolve() != target:
            _DEFAULT_DB = Database(target)
            _DEFAULT_DB.migrate()
        return _DEFAULT_DB
