"""The application's PostgreSQL database type and shared date utilities."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .postgres_db import PostgresDatabase as Database


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_today_str() -> str:
    # Quota accounting uses the product's business day across all workers.
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
