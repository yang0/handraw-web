"""Converge legacy ``work_comments`` into each work's discussion topic.

After the change every work reads its comments from ``forum_replies`` through
the ``origin='submission'`` mapping.  Older works still keep their comments in
``work_comments``; this script copies them across once, using
``forum_replies.legacy_source`` to stay idempotent, then flips the mapping so
the reader path is the same for old and new works.

Comments are inserted with ``status='migrating'`` and only afterwards updated to
their real status, because the notification trigger fires only on
``INSERT ... status='published'``.  Without that step the migration would
re-notify every author about historical comments.

Usage (dry run first, always):
    python -X utf8 ops/converge_work_comments.py --db .local/handraw_v2.db
    python -X utf8 ops/converge_work_comments.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

LEGACY_ORIGIN = "legacy"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def plan(conn: sqlite3.Connection) -> list[dict]:
    """Return the comments that still need copying."""
    mappings = conn.execute(
        "SELECT target_id, topic_id FROM curation_resource_topics WHERE kind = 'work' AND origin = ?",
        (LEGACY_ORIGIN,),
    ).fetchall()
    todo: list[dict] = []
    for mapping in mappings:
        work_id = str(mapping["target_id"])
        topic_id = str(mapping["topic_id"])
        comments = conn.execute(
            # Every status, not just published: after the mapping flips to
            # ``submission`` the reader only looks at forum_replies, so leaving
            # hidden or pending comments behind would lose them permanently.
            "SELECT * FROM work_comments WHERE work_id = ? ORDER BY created_at",
            (work_id,),
        ).fetchall()
        for comment in comments:
            source = f"work_comments:{comment['id']}"
            already = conn.execute(
                "SELECT 1 FROM forum_replies WHERE legacy_source = ?", (source,)
            ).fetchone()
            if already:
                continue
            todo.append(
                {
                    "workId": work_id,
                    "topicId": topic_id,
                    "comment": dict(comment),
                    "legacySource": source,
                }
            )
    return todo


def apply(conn: sqlite3.Connection, todo: list[dict]) -> int:
    now = _now()
    copied = 0
    for item in todo:
        comment = item["comment"]
        reply_id = f"reply_{uuid.uuid4().hex[:16]}"
        conn.execute(
            """
            INSERT INTO forum_replies (
                id, topic_id, author_username, author_name, text,
                mounted_style, mounted_layout, likes, accepted, status, time_label, created_at, legacy_source
            ) VALUES (?, ?, ?, ?, ?, '', '', ?, 0, 'migrating', ?, ?, ?)
            """,
            (
                reply_id,
                item["topicId"],
                str(comment.get("author_username") or ""),
                str(comment.get("author_name") or ""),
                str(comment.get("text") or ""),
                0,
                str(comment.get("time_label") or ""),
                str(comment.get("created_at") or now),
                item["legacySource"],
            ),
        )
        # Promote to the original status only now, so the notification trigger
        # does not fire for historical content.
        conn.execute(
            "UPDATE forum_replies SET status = ? WHERE id = ?",
            (str(comment.get("status") or "published"), reply_id),
        )
        copied += 1

    # Flip the mapping so both old and new works read comments the same way.
    conn.execute(
        "UPDATE curation_resource_topics SET origin = 'submission' WHERE kind = 'work' AND origin = ?",
        (LEGACY_ORIGIN,),
    )
    conn.commit()
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy legacy work comments into forum replies.")
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 2

    conn = _connect(db_path)
    try:
        todo = plan(conn)
        print(f"待迁移评论：{len(todo)} 条")
        if todo:
            by_work: dict[str, int] = {}
            for item in todo:
                by_work[item["workId"]] = by_work.get(item["workId"], 0) + 1
            for work_id, count in sorted(by_work.items())[:10]:
                print(f"  {work_id}: {count}")
            if len(by_work) > 10:
                print(f"  ... 另有 {len(by_work) - 10} 件作品")
        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0
        if not todo:
            print("没有需要迁移的评论。")
            return 0

        backup = db_path.with_name(db_path.name + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(db_path, backup)
        print(f"已备份：{backup}")
        copied = apply(conn, todo)
        print(f"已迁移 {copied} 条，映射已改为 submission。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
