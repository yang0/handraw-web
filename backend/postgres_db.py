"""PostgreSQL connection pool, transactions, and application SQL adapter."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from contextlib import contextmanager
from functools import cached_property, lru_cache

from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

from .observability import local_debug_stacks_enabled, sanitize_log_text


class HybridRow(dict):
    """A result row with named and positional column access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


@lru_cache(maxsize=512)
def _placeholders(query: str) -> str:
    """Convert qmark parameters and escape literal driver-format percent signs."""
    buf = []
    i = 0
    mode = ""
    while i < len(query):
        c = query[i]
        nxt = query[i + 1] if i + 1 < len(query) else ""
        if c == "%":
            buf.append("%%")
            i += 1
            continue
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


class PgCursor:
    def __init__(self, cursor):
        self._cur = cursor
        self.rowcount = cursor.rowcount
        self.description = cursor.description

    def _row(self, raw):
        if raw is None:
            return None
        if self.description is None:
            return raw
        return HybridRow({col.name: value for col, value in zip(self.description, raw)})

    def fetchone(self):
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

    @cached_property
    def cache_scope(self) -> str:
        info = self._db.info
        database_endpoint = (info.host, info.port, info.dbname)
        return hashlib.sha256(repr(database_endpoint).encode("utf-8")).hexdigest()

    def execute(self, statement, params=()):
        q = _placeholders(str(statement)) if params else str(statement)
        cur = self._db.cursor()
        try:
            cur.execute(q, tuple(params) if params else None)
            return PgCursor(cur)
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
        q = _placeholders(str(statement)) if rows else str(statement)
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
            cursor.execute("""SELECT to_regclass('public.article_illustrations') IS NOT NULL
                              AND to_regclass('public.studio_canvases') IS NOT NULL
                              AND EXISTS(SELECT 1 FROM public.schema_migrations WHERE version=118)""")
            if not cursor.fetchone()[0]:
                raise RuntimeError("Missing studio schema. Apply backend/postgres_118_studio_model.sql and run ops/upgrade_studio_model.py before starting this code")
            cursor.execute("SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version=119)")
            if not cursor.fetchone()[0]:
                raise RuntimeError("Apply backend/postgres_119_economy.sql before starting")
            cursor.execute("SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version=120)")
            if not cursor.fetchone()[0]:
                raise RuntimeError("Apply backend/postgres_120_contribution_guards.sql before starting")
            cursor.execute("SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version=121)")
            if not cursor.fetchone()[0]:
                raise RuntimeError("Apply backend/postgres_121_reward_promotions.sql before starting")
        return []

    def close_thread_conn(self):
        wrapper = getattr(self._local, "wrapper", None)
        if wrapper:
            self._local.wrapper = None
            self._pool.putconn(wrapper._db)

    def release_request_connection(self):
        wrapper = getattr(self._local, "wrapper", None)
        if wrapper and wrapper._db.info.transaction_status != TransactionStatus.IDLE:
            raise RuntimeError("Cannot release a PostgreSQL connection inside an active transaction")
        self.close_thread_conn()

    def close(self):
        dispatcher = getattr(self, "_canvas_dispatcher", None)
        if dispatcher is not None:
            dispatcher.stop()
        manager = getattr(self, "_import_manager", None)
        if manager is not None:
            manager.stop()
        self.close_thread_conn()
        self._pool.close()
