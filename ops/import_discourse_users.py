#!/usr/bin/env python3
"""Additive, idempotent CLI importer for migrating existing Discourse registered users into Handraw Web 2.0.

Supports JSON arrays/objects (with keys such as `username`, `email`,
`password_hash`, `password_salt`, `google_uid`, and `email_verified`) or CSV
exports from Discourse PostgreSQL (`users`, `user_emails`, `user_passwords`,
and `user_associated_accounts`) without touching the production Discourse DB.

Example PostgreSQL export on Discourse 3.2+ host (run outside repo into a non-committed path):
    psql -d discourse -c "\\copy (
      SELECT json_agg(t) FROM (
        SELECT u.id, u.username, u.name, ue.email, pw.password_hash, pw.password_salt,
               ga.provider_uid AS google_uid, true AS email_verified,
               u.admin, u.moderator, u.created_at
        FROM users u
        JOIN user_emails ue ON ue.user_id = u.id AND ue.primary = true
        LEFT JOIN LATERAL (
          SELECT password_hash, password_salt FROM user_passwords up
          WHERE up.user_id = u.id ORDER BY up.created_at DESC LIMIT 1
        ) pw ON true
        LEFT JOIN LATERAL (
          SELECT provider_uid FROM user_associated_accounts ua
          WHERE ua.user_id = u.id AND ua.provider_name = 'google_oauth2'
          ORDER BY ua.last_used DESC NULLS LAST LIMIT 1
        ) ga ON true
        WHERE u.id > 0 AND u.active = true AND u.staged = false
        ORDER BY u.id
      ) t
    ) TO '/tmp/discourse_users.json'"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.postgres_db import PostgresDatabase
from backend.services import import_discourse_users_batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Discourse users into the PostgreSQL database configured in HANDRAW_DATABASE_URL.")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Path to CSV or JSON export of Discourse users")
    parser.add_argument(
        "--migration-credits",
        type=int,
        default=None,
        help="Optional welcome credit grant per migrated user (defaults to site_settings.economy.discourse_migration_credits)",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    raw_text = args.input.read_text(encoding="utf-8")
    dsn = os.environ.get("HANDRAW_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("Set HANDRAW_DATABASE_URL to the target PostgreSQL database")
    with closing(PostgresDatabase(dsn)) as db:
        db.migrate()
        result = import_discourse_users_batch(
            db,
            actor={"id": None, "username": "cli_ops", "role": "admin"},
            raw_payload=raw_text,
            migration_credits=args.migration_credits,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
