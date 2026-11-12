"""Re-label starter accounts as official examples instead of fake creators.

The starter library seeds real works so the square is not empty on day one.
Those accounts must not impersonate community members: ``product-direction.md``
requires a real content environment with no test accounts, and a fabricated
"new creator" persona would violate that the moment someone checks.

This script only changes presentation:
  * display name gets an explicit official marker,
  * bio states it is an example,
  * role stays ``user`` so nothing about permissions changes.

Usage:
    python -X utf8 ops/label_starter_accounts.py
    python -X utf8 ops/label_starter_accounts.py --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops.postgres_maintenance import backup_before_change, configure_transaction, maintenance_database, maintenance_parser

STARTER_USERNAMES = ("linnan", "chenmo", "yuzi_art", "helan", "tangyuan")
OFFICIAL_BIO = "官方示例账号 · 内容由官方整理发布，用于展示画风与图型的实际效果"


def plan(db) -> list[dict]:
    conn = db.get_conn()
    out: list[dict] = []
    placeholders = ", ".join("?" for _ in STARTER_USERNAMES)
    rows = conn.execute(
        f"SELECT username, display_name, bio FROM users WHERE username IN ({placeholders})",
        STARTER_USERNAMES,
    )
    by_username = {row["username"]: row for row in rows}
    for username in STARTER_USERNAMES:
        row = by_username.get(username)
        if not row:
            continue
        display = str(row["display_name"] or username)
        if display.startswith("官方示例"):
            continue
        out.append(
            {
                "username": username,
                "before": {"displayName": display, "bio": str(row["bio"] or "")},
                "after": {"displayName": f"官方示例·{display}", "bio": OFFICIAL_BIO},
            }
        )
    return out


def apply(db, todo: list[dict]) -> int:
    changed = 0
    with db.transaction() as tx:
        for item in todo:
            changed += tx.execute(
                "UPDATE users SET display_name = ?, bio = ? WHERE username = ?",
                (item["after"]["displayName"], item["after"]["bio"], item["username"]),
            ).rowcount
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = maintenance_parser("Label starter accounts as official examples.")
    args = parser.parse_args(argv)
    with maintenance_database(parser) as (db, dsn), db.transaction() as conn:
        configure_transaction(conn, write=args.apply)
        todo = plan(db)
        print(f"待标注账号：{len(todo)}")
        for item in todo:
            print(f"  {item['username']}: {item['before']['displayName']} -> {item['after']['displayName']}")
        if not args.apply or not todo:
            return 0
        backup = backup_before_change(conn, dsn, args.backup_dir, "starter-labels-before")
        print(f"已验证备份：{backup}")
        changed = apply(db, todo)
    print(f"已标注 {changed} 个账号。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
