"""Create and dispose of independent PostgreSQL databases for integration tests."""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from ops.bootstrap_postgres_v3 import bootstrap


@contextmanager
def isolated_pg_dsn():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    admin_dsn = os.environ["HANDRAW_PG_STAGING_URL"]
    name = "handraw_test_" + uuid.uuid4().hex
    identifier = sql.Identifier(name)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
        try:
            dsn = make_conninfo(admin_dsn, dbname=name)
            with patch.dict(os.environ, {"HANDRAW_ALLOW_PG_BOOTSTRAP": "YES"}):
                bootstrap(dsn=dsn, apply=True)
            yield dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(identifier))
