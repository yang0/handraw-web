"""Disposable PostgreSQL fixture for standalone browser acceptance scripts.

The database lives until the script exits so a child API process can share it
after the seeding connection pool closes. No production database is accepted.
"""
import atexit
from contextlib import ExitStack
import os
from unittest.mock import patch

from backend.postgres_db import PostgresDatabase
from backend.seed import ensure_seeded
from tests.postgres_support import isolated_pg_dsn

_resources = ExitStack()
atexit.register(_resources.close)


def browser_postgres_database():
    if not os.environ.get("HANDRAW_PG_STAGING_URL"):
        raise RuntimeError("Browser verification requires HANDRAW_PG_STAGING_URL for disposable databases")
    dsn = _resources.enter_context(isolated_pg_dsn())
    db = PostgresDatabase(dsn)
    _resources.callback(db.close)
    ensure_seeded(db)
    _resources.enter_context(patch.dict(os.environ, {"HANDRAW_DATABASE_URL": dsn}))
    return db
