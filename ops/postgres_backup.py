"""Write private PostgreSQL archives for maintenance commands."""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


def dump_snapshot(dsn: str, snapshot: str, directory: Path) -> Path:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    pg_dump = shutil.which("pg_dump")
    if not pg_dump and os.name == "nt":
        installed = Path(r"D:\PostgreSQL\pgsql\bin\pg_dump.exe")
        if installed.is_file():
            pg_dump = str(installed)
    if not pg_dump:
        raise RuntimeError("pg_dump is required to back up PostgreSQL before repair")

    settings = conninfo_to_dict(dsn)
    env = os.environ.copy()
    password = settings.pop("password", None)
    if password is not None:
        env["PGPASSWORD"] = password

    directory = directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"social-counters-before-{stamp}-{uuid4().hex[:8]}.dump"
    with TemporaryDirectory(prefix="handraw-pg-backup-", dir=directory) as temp:
        staging = Path(temp) / "snapshot.dump"
        ssl_password = settings.pop("sslpassword", None)
        if ssl_password is not None:
            # libpq accepts the key password from a service file, with no environment variable.
            settings["sslpassword"] = ssl_password
            if any("\n" in value or "\r" in value for value in settings.values()):
                raise ValueError("Connection settings cannot be represented in a libpq service file")
            service_file = Path(temp) / "pg_service.conf"
            service_file.write_text("[handraw_backup]\n" + "".join(f"{key}={value}\n" for key, value in settings.items()), encoding="utf-8")
            env["PGSERVICEFILE"] = str(service_file)
            connection = "service=handraw_backup"
        else:
            connection = make_conninfo(**settings)

        subprocess.run(
            [pg_dump, "--no-password", "--format=custom", "--dbname", connection,
             "--snapshot", snapshot, "--file", str(staging)],
            env=env, check=True,
        )
        if staging.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty archive")
        staging.chmod(0o600)
        staging.replace(destination)
    return destination
