"""PostgreSQL connection pool, transactions, and application SQL adapter."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from contextlib import contextmanager
from functools import cached_property

from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

from .observability import local_debug_stacks_enabled, sanitize_log_text


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
    # The development schema uses SQLite's built-in NOCASE collation. On PG,
    # make explicit case-insensitive comparisons rather than requiring a
    # non-portable ICU collation installed by the database administrator.
    case_cmp = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*(=|!=|<>)\s*(%s)\s+COLLATE\s+NOCASE\b",
        re.I,
    )
    q = case_cmp.sub(
        lambda m: f"lower({m.group(1)}::text) {m.group(2)} lower({m.group(3)}::text)", q,
    )
    case_column = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_.]*)\s+COLLATE\s+NOCASE\s*(=|!=|<>)\s*(%s)",
        re.I,
    )
    q = case_column.sub(
        lambda m: f"lower({m.group(1)}::text) {m.group(2)} lower({m.group(3)}::text)", q,
    )
    q = re.sub(r"\s+COLLATE\s+NOCASE\b", "", q, flags=re.I)
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
    q = re.sub(r"\bCOALESCE\(\s*gw\.rowid\s*,\s*0\s*\)", "0", q, flags=re.I)
    q = re.sub(r"\bgw\.rowid\b", "0", q, flags=re.I)
    q = re.sub(r"\browid\b", "id", q, flags=re.I)
    # SQLite MAX(x,y) is scalar; PostgreSQL MAX() is an aggregate.
    # The site uses MAX(0, counter - n) for atomic nonnegative decrements.
    # SQLite also accepts MAX(column, literal) as a scalar function, while
    # PostgreSQL reserves MAX(column) for aggregate calculations.
    q = re.sub(
        r"\bMAX\(\s*([A-Za-z_][A-Za-z_0-9.]*|[-+]?\d+)\s*,",
        lambda m: "GREATEST(" + m.group(1) + ",", q, flags=re.I,
    )
    q = re.sub(
        r"\bMIN\(\s*([A-Za-z_][A-Za-z_0-9.]*|[-+]?\d+)\s*,",
        lambda m: "LEAST(" + m.group(1) + ",", q, flags=re.I,
    )
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
    dialect = "postgresql"

    def __init__(self, connection):
        self._db = connection
        self._identity: dict[str, str | None] = {}

    @cached_property
    def cache_scope(self) -> str:
        info = self._db.info
        database_endpoint = (info.host, info.port, info.dbname)
        return hashlib.sha256(repr(database_endpoint).encode("utf-8")).hexdigest()

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
                self._identity[table] = rows[0][0] if rows else None
            identity_col = self._identity.get(table)
            if identity_col and not re.search(r"\bRETURNING\b", q, re.I):
                q = q.rstrip().rstrip(";") + f' RETURNING "{identity_col}"'
                identity = True
        cur = self._db.cursor()
        try:
            cur.execute(q, tuple(params or ()))
            return PgCursor(cur, returning_identity=identity)
        except BaseException as exc:
            cur.close()
            if not isinstance(exc, (KeyboardInterrupt, SystemExit)) and local_debug_stacks_enabled():
                logging.getLogger("handraw.trace").info(
                    "pg_execute_error statement=%s",
                    sanitize_log_text(q, max_len=160),
                    exc_info=True,
                )
            raise

    def executemany(self, statement, seq_of_params):
        rows = [tuple(p) for p in seq_of_params]
        q = _rewrite(str(statement))
        cur = self._db.cursor()
        try:
            if rows:
                cur.executemany(q, rows)
            return PgCursor(cur)
        except BaseException as exc:
            cur.close()
            if not isinstance(exc, (KeyboardInterrupt, SystemExit)) and local_debug_stacks_enabled():
                logging.getLogger("handraw.trace").info(
                    "pg_executemany_error statement=%s rows=%d",
                    sanitize_log_text(q, max_len=160),
                    len(rows),
                    exc_info=True,
                )
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


def _configure_connection(connection):
    # Configure each physical connection before it enters the pool.
    connection.execute("""
        SELECT set_config('statement_timeout', '30s', false),
               set_config('lock_timeout', '5s', false),
               set_config('idle_in_transaction_session_timeout', '60s', false)
    """)


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
            configure=_configure_connection, open=True,
        )

    def get_conn(self):
        wrapper = getattr(self._local, "wrapper", None)
        if wrapper is None or wrapper._db.closed:
            raw = self._pool.getconn()
            wrapper = PgConnection(raw)
            self._local.wrapper = wrapper
        return wrapper

    @contextmanager
    def transaction(self):
        conn = self.get_conn()
        with conn._db.transaction():
            yield conn

    def migrate(self):
        # Startup validates the installed schema with the application's role.
        # Schema changes are applied separately by the database owner.
        conn = self.get_conn()
        with conn._db.cursor() as cursor:
            cursor.execute(
                """SELECT to_regclass('public.schema_migrations'),
                          to_regclass('public.users'),
                          to_regclass('public.works'),
                          to_regclass('public.generation_runs'),
                          to_regclass('public.generation_items'),
                          to_regclass('public.media_assets'),
                          to_regclass('public.work_media'),
                          to_regclass('public.media_gc_jobs'),
                          to_regclass('public.home_scenarios'),
                          to_regclass('public.scenario_pinned_works')"""
            )
            required_tables = cursor.fetchone()
            if not all(required_tables):
                raise RuntimeError(
                    "PostgreSQL V3 schema is missing. Initialize an EMPTY "
                    "database with python -m ops.bootstrap_postgres_v3 --apply"
                )
            cursor.execute("SELECT 1 FROM schema_migrations WHERE version=100 LIMIT 1")
            if not cursor.fetchone():
                raise RuntimeError("Missing native V3 schema baseline and media GC (migration 100)")
            cursor.execute(
                """SELECT expected.trigger_name
                   FROM (VALUES
                       ('public.generation_runs'::regclass, 'v3_run_immutable'),
                       ('public.generation_items'::regclass, 'v3_gen_item_owner'),
                       ('public.media_assets'::regclass, 'v3_media_immutable'),
                       ('public.work_media'::regclass, 'v3_work_media_owner'),
                       ('public.work_media'::regclass, 'v3_cover_media_delete'),
                       ('public.works'::regclass, 'v3_work_run_owner'),
                       ('public.works'::regclass, 'v3_work_cover'),
                       ('public.works'::regclass, 'v3_work_images_cache')
                   ) AS expected(table_id, trigger_name)
                   WHERE NOT EXISTS (
                       SELECT 1 FROM pg_catalog.pg_trigger AS t
                       WHERE t.tgrelid = expected.table_id AND t.tgname = expected.trigger_name
                         AND t.tgenabled IN ('O', 'A') AND NOT t.tgisinternal
                   )"""
            )
            missing_triggers = [row[0] for row in cursor.fetchall()]
            if missing_triggers:
                raise RuntimeError("Native V3 integrity triggers missing or disabled: " + ", ".join(missing_triggers))
            cursor.execute("""
                SELECT to_regprocedure('public.json_valid(text)'),
                       to_regprocedure('public.json_array_length(text)'),
                       to_regprocedure('public.json_each(text)')
            """)
            if not all(cursor.fetchone()):
                raise RuntimeError("PostgreSQL V3 JSON functions are missing. Check the native schema installation.")
            cursor.execute("""
                SELECT to_regclass('public.payment_orders') IS NOT NULL
                   AND to_regclass('public.payment_webhook_events') IS NOT NULL
                   AND EXISTS (
                       SELECT 1 FROM public.schema_migrations
                       WHERE version=111 AND name='111_payment_billing_orders'
                   )
            """)
            if not cursor.fetchone()[0]:
                raise RuntimeError(
                    "Missing PostgreSQL billing schema. Apply backend/postgres_111_payment_billing.sql"
                )
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
