"""PostgreSQL compatibility adapter for staged Handraw v2 accounts.

This adapter is intentionally opt-in during parity testing. PostgreSQL schema
must first be staged and verified: it cannot execute SQLite DDL/migrations.
Unlike the production SQLite manager, it uses real DB transactions and a
thread-local PG connection rather than a process-local write mutex.

The SQL dialect shim is deliberately conservative: unsupported SQLite-specific
SQL MUST raise an error. Do not use as the public default until all business
routes and concurrency invariants pass PostgreSQL integration tests.
"""
from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager

from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool


class HybridRow(dict):
    """SQL row supports both sqlite3.Row['name'] and sqlite3.Row[0]."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _placeholders(query: str) -> str:
    """Translate SQLite qmarks only outside SQL string/comment literals."""
    buf = []
    i = 0
    mode = ""
    while i < len(query):
        c = query[i]
        nxt = query[i + 1] if i + 1 < len(query) else ""
        if not mode:
            if c == "'":
                mode = "'"
            elif c == '"':
                mode = '"'
            elif c == "-" and nxt == "-":
                mode = "--"
                buf.extend(("-", "-"))
                i += 2
                continue
            elif c == "/" and nxt == "*":
                mode = "/*"
                buf.extend(("/", "*"))
                i += 2
                continue
            elif c == "?":
                buf.append("%s")
                i += 1
                continue
        elif mode in {"'", '"'}:
            if c == mode and nxt == mode:
                buf.extend((c, nxt))
                i += 2
                continue
            if c == mode:
                mode = ""
        elif mode == "--" and c == "\n":
            mode = ""
        elif mode == "/*" and c == "*" and nxt == "/":
            mode = ""
            buf.extend(("*", "/"))
            i += 2
            continue
        buf.append(c)
        i += 1
    return "".join(buf)


def _rewrite(query: str) -> str:
    q = _placeholders(query)
    if re.search(r"\b(PRAGMA|sqlite_master|last_insert_rowid|executescript)\b", q, re.I):
        raise ValueError("Unsupported SQLite-specific SQL in PostgreSQL runtime")
    ignore = bool(re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\b", q, re.I))
    if ignore:
        q = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", q, count=1, flags=re.I)
        if "ON CONFLICT" not in q.upper():
            q = q.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    if re.search(r"\bINSERT\s+OR\s+REPLACE\b", q, re.I):
        raise ValueError("INSERT OR REPLACE requires an explicit UPSERT before PG deployment")
    # SQLite expression compatibility for frequently used time literals.
    q = re.sub(r"\bstrftime\(\s*'%s'\s*,\s*'now'\s*\)",
               "floor(extract(epoch from now()))::bigint", q, flags=re.I)
    q = re.sub(r"\bstrftime\(\s*'%Y-%m-%d'\s*,\s*'now'\s*\)",
               "(now() at time zone 'utc')::date::text", q, flags=re.I)
    q = re.sub(r"\bstrftime\(\s*'%Y-%m-%dT%H:%M:%SZ'\s*,\s*'now'\s*\)",
               """to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')""", q, flags=re.I)
    q = re.sub(r"\bdate\(\s*'now'\s*\)", "(now() at time zone 'utc')::date::text", q, flags=re.I)
    q = re.sub(r"\bdate\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
               lambda m: "left(" + m.group(1) + ",10)", q, flags=re.I)
    q = re.sub(r"\bstrftime\(\s*'%s'\s*,\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
               lambda m: "floor(extract(epoch from (" + m.group(1) + ")::timestamp))::bigint", q, flags=re.I)
    if re.search(r"\b(strftime|julianday|json_extract|datetime\s*\()\s*\(", q, re.I):
        raise ValueError("SQLite SQL expression needs explicit PostgreSQL port")
    return q


class PgCursor:
    def __init__(self, cursor, *, returning_identity: bool = False):
        self._cur = cursor
        self.rowcount = cursor.rowcount
        self.description = cursor.description
        self.lastrowid = None
        self._preloaded = []
        if returning_identity:
            result = cursor.fetchone()
            if result:
                self.lastrowid = int(result[0])

    def _row(self, raw):
        if raw is None:
            return None
        if self.description is None:
            return raw
        return HybridRow({col.name: value for col, value in zip(self.description, raw)})

    def fetchone(self):
        if self._preloaded:
            return self._preloaded.pop(0)
        return self._row(self._cur.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self._cur.fetchall()]

    def __iter__(self):
        for row in self._cur:
            yield self._row(row)

    def close(self):
        self._cur.close()


class PgConnection:
    def __init__(self, connection):
        self._db = connection
        self._identity = set()

    def execute(self, statement, params=()):
        source = str(statement)
        q = _rewrite(source)
        identity = False
        match = re.match(r"\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z_0-9]*)\b", q, re.I)
        if match:
            table = match.group(1)
            if table not in self._identity:
                # Only tables with a PostgreSQL IDENTITY column need RETURNING.
                with self._db.cursor() as introspect:
                    introspect.execute(
                        """SELECT column_name FROM information_schema.columns
                           WHERE table_schema='public' AND table_name=%s
                             AND is_identity='YES'""", (table,)
                    )
                    rows = introspect.fetchall()
                if rows:
                    self._identity.add(table)
            if table in self._identity and not re.search(r"\bRETURNING\b", q, re.I):
                q = q.rstrip().rstrip(";") + " RETURNING id"
                identity = True
        cur = self._db.cursor()
        try:
            cur.execute(q, tuple(params or ()))
            return PgCursor(cur, returning_identity=identity)
        except BaseException:
            cur.close()
            raise

    def commit(self):
        self._db.commit()

    def rollback(self):
        self._db.rollback()

    def close(self):
        self._db.close()

    @property
    def in_transaction(self):
        return self._db.info.transaction_status == TransactionStatus.INTRANS


class PostgresDatabase:
    """Thread-local psycopg connection with the Database.transaction contract."""

    def __init__(self, dsn: str):
        try:
            parsed = conninfo_to_dict(dsn)
        except Exception as exc:
            raise ValueError("Expected a valid PostgreSQL connection string") from exc
        if not isinstance(dsn, str) or not dsn.strip() or not parsed.get("dbname"):
            raise ValueError("PostgreSQL connection string must specify dbname")
        self.db_path = "PostgreSQL (configured URL)"
        self._dsn = dsn
        self._local = threading.local()
        self._write_lock = threading.RLock()  # legacy local critical sections only
        size = min(32, max(2, int(os.environ.get("HANDRAW_PG_POOL_SIZE", "12"))))
        self._pool = ConnectionPool(
            conninfo=dsn, min_size=1, max_size=size, timeout=5.0,
            kwargs={"autocommit": True, "connect_timeout": 5},
            open=True,
        )

    def get_conn(self):
        wrapper = getattr(self._local, "wrapper", None)
        if wrapper is None or wrapper._db.closed:
            raw = self._pool.getconn()
            raw.execute("SET statement_timeout = '30s'")
            raw.execute("SET lock_timeout = '5s'")
            raw.execute("SET idle_in_transaction_session_timeout = '60s'")
            wrapper = PgConnection(raw)
            self._local.wrapper = wrapper
        return wrapper

    @contextmanager
    def transaction(self):
        conn = self.get_conn()
        with conn._db.transaction():
            yield conn

    def migrate(self):
        # Explicitly fail if migrations were not staged; NEVER execute SQLite
        # DDL against PostgreSQL or silently initialize a second local DB.
        conn = self.get_conn()
        with conn._db.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.schema_migrations'), to_regclass('public.users')"
            )
            versions, users = cursor.fetchone()
            if not versions or not users:
                raise RuntimeError("PostgreSQL schema not imported; initialize and validate staging first")
        return []

    def close_thread_conn(self):
        wrapper = getattr(self._local, "wrapper", None)
        if wrapper:
            self._local.wrapper = None
            self._pool.putconn(wrapper._db)

    def release_request_connection(self):
        self.close_thread_conn()

    def close(self):
        self.close_thread_conn()
        self._pool.close()
