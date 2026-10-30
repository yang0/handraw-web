"""Converge legacy ``work_comments`` into each work's discussion topic.

After the change every work reads its comments from ``forum_replies`` through
the ``origin='submission'`` mapping. Older works still keep their comments in
``work_comments``; this script copies them across once, using
``forum_replies.legacy_source`` to stay idempotent, then flips the mapping so
the reader path is the same for old and new works.

Comments are inserted with ``status='migrating'`` and only afterwards updated to
their real status, because the notification trigger fires only on
``INSERT ... status='published'``. Without that step the migration would
re-notify every author about historical comments.

Usage (dry run first, always):
    python -X utf8 ops/converge_work_comments.py --db .local/handraw_v2.db
    python -X utf8 ops/converge_work_comments.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import services as S

LEGACY_ORIGIN = "legacy"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def backup(conn: sqlite3.Connection, db_path: Path) -> Path:
    """Copy the database through SQLite's backup API and verify integrity."""
    target = db_path.with_name(db_path.name + f".bak-work-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()

    verify = sqlite3.connect(str(target))
    try:
        verify.execute("SELECT COUNT(*) FROM forum_topics").fetchone()
    except Exception as e:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"备份数据库完整性验证失败：{e}") from e
    finally:
        verify.close()
    return target


def plan(conn: sqlite3.Connection) -> list[dict]:
    """Return the comments that still need copying. Starts from unmigrated comments (K3)."""
    seed_wc = S.seed_ids("work_comments")

    unmigrated = conn.execute(
        """
        SELECT wc.* FROM work_comments wc
        WHERE wc.status <> 'migrated'
          AND NOT EXISTS (
              SELECT 1 FROM forum_replies fr WHERE fr.legacy_source = 'work_comments:' || wc.id
          )
        ORDER BY wc.created_at ASC
        """
    ).fetchall()

    todo: list[dict] = []
    for c in unmigrated:
        cid = str(c["id"])
        if cid in seed_wc:
            continue
        wid = str(c["work_id"])
        source = f"work_comments:{cid}"

        # 1. Existing curation mapping
        mapping = conn.execute(
            "SELECT topic_id, origin FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
            (wid,),
        ).fetchone()
        topic_id = str(mapping["topic_id"]) if mapping else None

        # 2. Existing forum_topics row by work_id
        if not topic_id:
            t_row = conn.execute(
                "SELECT id FROM forum_topics WHERE work_id = ?",
                (wid,),
            ).fetchone()
            if t_row:
                topic_id = str(t_row["id"])

        todo.append({
            "workId": wid,
            "topicId": topic_id,
            "comment": dict(c),
            "legacySource": source,
        })

    return todo


def apply(conn: sqlite3.Connection, todo: list[dict]) -> tuple[int, list[str]]:
    from backend.resource_discussions import ensure_topic

    now = _now()
    copied = 0
    failures: list[str] = []
    work_failures: dict[str, list[str]] = {}
    work_counts: dict[str, int] = {}

    # Ensure topic & mapping exist for works needing migration (L2 / L3)
    created_topics: dict[str, str] = {}
    for item in todo:
        wid = item["workId"]
        tid = item.get("topicId") or created_topics.get(wid)
        if not tid:
            w_row = conn.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone()
            if not w_row:
                err = f"找不到作品记录：work_id={wid}"
                failures.append(err)
                work_failures.setdefault(wid, []).append(err)
                continue
            tid = ensure_topic(conn, "work", wid, dict(w_row), initial_origin="legacy")
            created_topics[wid] = tid

        # Ensure mapping with origin='legacy' exists before migration
        conn.execute(
            "INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', ?, ?, 'legacy', ?)",
            (wid, tid, S.utc_now_iso()),
        )

    for item in todo:
        wid = item["workId"]
        work_counts[wid] = work_counts.get(wid, 0) + 1
        topic_id = item.get("topicId") or created_topics.get(wid)
        if not topic_id:
            m = conn.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (wid,)).fetchone()
            if m:
                topic_id = str(m["topic_id"])
        if not topic_id:
            err = f"缺少目标讨论帖，跳过评论：{item['legacySource']}"
            failures.append(err)
            work_failures.setdefault(wid, []).append(err)
            continue

        already = conn.execute(
            "SELECT 1 FROM forum_replies WHERE legacy_source = ?", (item["legacySource"],)
        ).fetchone()
        if already:
            # Still ensure status is updated to migrated
            conn.execute("UPDATE work_comments SET status = 'migrated' WHERE id = ?", (item["comment"]["id"],))
            continue

        comment = item["comment"]
        reply_id = f"reply_{uuid.uuid4().hex[:16]}"
        st = str(comment.get("status") or "published")
        actor_role = comment.get("status_actor_role")
        if not actor_role and st == "hidden":
            actor_role = "admin"
        else:
            actor_role = str(actor_role or "")

        conn.execute("SAVEPOINT copy_work_comment")
        try:
            conn.execute(
                """
                INSERT INTO forum_replies (
                    id, topic_id, author_username, author_name, text,
                    mounted_style, mounted_layout, likes, accepted, status, time_label, created_at, legacy_source, status_actor_role
                ) VALUES (?, ?, ?, ?, ?, '', '', ?, 0, 'migrating', ?, ?, ?, ?)
                """,
                (
                    reply_id,
                    topic_id,
                    str(comment.get("author_username") or ""),
                    str(comment.get("author_name") or ""),
                    str(comment.get("text") or ""),
                    0,
                    str(comment.get("time_label") or ""),
                    str(comment.get("created_at") or now),
                    item["legacySource"],
                    actor_role,
                ),
            )
            conn.execute(
                "UPDATE forum_replies SET status = ?, status_actor_role = ? WHERE id = ?",
                (st, actor_role, reply_id),
            )
            # K2: Mark old record as migrated in the same SAVEPOINT
            conn.execute(
                "UPDATE work_comments SET status = 'migrated' WHERE id = ?",
                (comment["id"],),
            )
            conn.execute("RELEASE SAVEPOINT copy_work_comment")
            copied += 1
        except Exception as e:
            conn.execute("ROLLBACK TO SAVEPOINT copy_work_comment")
            err = f"{item['legacySource']}: {e}"
            failures.append(err)
            work_failures.setdefault(wid, []).append(err)

    # Flip mapping only for works that had zero failures
    for wid in work_counts:
        if wid not in work_failures:
            conn.execute(
                "UPDATE curation_resource_topics SET origin = 'submission' WHERE kind = 'work' AND target_id = ?",
                (wid,),
            )

    conn.commit()
    return copied, failures


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

        bak_path = backup(conn, db_path)
        print(f"已备份并通过验证：{bak_path}")
        copied, failures = apply(conn, todo)
        print(f"已迁移 {copied} 条。")
        if failures:
            print(f"迁移存在 {len(failures)} 处失败清单：", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
