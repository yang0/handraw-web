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
    python -X utf8 ops/label_starter_accounts.py --db .local/handraw_v2.db
    python -X utf8 ops/label_starter_accounts.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STARTER_USERNAMES = ("linnan", "chenmo", "yuzi_art", "helan", "tangyuan")
OFFICIAL_BIO = "官方示例账号 · 内容由官方整理发布，用于展示画风与图型的实际效果"


def plan(db) -> list[dict]:
    conn = db.get_conn()
    out: list[dict] = []
    for username in STARTER_USERNAMES:
        row = conn.execute(
            "SELECT username, display_name, bio FROM users WHERE username = ?", (username,)
        ).fetchone()
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
            tx.execute(
                "UPDATE users SET display_name = ?, bio = ? WHERE username = ?",
                (item["after"]["displayName"], item["after"]["bio"], item["username"]),
            )
            changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label starter accounts as official examples.")
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    from backend.db import Database

    db = Database(Path(args.db).resolve())
    db.migrate()
    try:
        todo = plan(db)
        print(f"待标注账号：{len(todo)}")
        for item in todo:
            print(f"  {item['username']}: {item['before']['displayName']} -> {item['after']['displayName']}")
        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0
        changed = apply(db, todo)
        print(f"已标注 {changed} 个账号。")
        return 0
    finally:
        db.close_thread_conn()
        db.get_conn().close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
