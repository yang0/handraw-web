#!/usr/bin/env python3
"""Additive, idempotent CLI importer for migrating existing Discourse registered users into Handraw Web 2.0.

Supports JSON arrays/objects (`[{"username":..., "email":..., "password_hash":..., "salt":...}]`)
or CSV exports from Discourse PostgreSQL (`users` + `user_emails`) without touching production Discourse DB.

Example PostgreSQL export on Discourse host (run outside repo into a non-committed path):
    psql -d discourse -c "\\copy (
      SELECT u.id, u.username, u.name, ue.email, u.password_hash, u.salt, u.admin, u.moderator, u.created_at
      FROM users u
      JOIN user_emails ue ON ue.user_id = u.id AND ue.primary = true
      WHERE u.id > 0 AND u.active = true AND u.staged = false
    ) TO '/tmp/discourse_users.csv' WITH CSV HEADER"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import get_db_path
from backend.server import init_database
from backend.services import import_discourse_users_batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Discourse users into Handraw Web 2.0 SQLite DB.")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Path to CSV or JSON export of Discourse users")
    parser.add_argument("--db", type=Path, default=None, help="Target Handraw Web 2.0 SQLite database path")
    parser.add_argument(
        "--migration-credits",
        type=int,
        default=None,
        help="Optional welcome credit grant per migrated user (defaults to site_settings.economy.discourse_migration_credits)",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    raw_text = args.input.read_text(encoding="utf-8")
    db = init_database(args.db or get_db_path())

    result = import_discourse_users_batch(
        db,
        actor={"id": 0, "username": "cli_ops", "role": "admin"},
        raw_payload=raw_text,
        migration_credits=args.migration_credits,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
