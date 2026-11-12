"""Copy one historical comment into its discussion without notifying the author."""
from __future__ import annotations

import uuid

from backend.db import utc_now_iso
from ops.postgres_maintenance import savepoint


def copy_comment(conn, source_table: str, item: dict, topic_id: str) -> int:
    comment = item["comment"]
    legacy_source = item["legacySource"]
    with savepoint(conn):
        existing = conn.execute(
            "SELECT 1 FROM forum_replies WHERE legacy_source <> '' AND legacy_source = ?", (legacy_source,),
        ).fetchone()
        if not existing:
            reply_id = "reply_" + uuid.uuid4().hex[:16]
            status = str(comment.get("status") or "published")
            role = str(comment.get("status_actor_role") or ("admin" if status == "hidden" else ""))
            cursor = conn.execute(
                """
                INSERT INTO forum_replies (
                    id, topic_id, author_username, author_name, text, mounted_style, mounted_layout,
                    likes, accepted, status, time_label, created_at, legacy_source, status_actor_role
                )
                SELECT ?, id, ?, ?, ?, '', '', 0, 0, 'migrating', ?, ?, ?, ?
                FROM forum_topics WHERE id = ?
                """,
                (
                    reply_id, str(comment.get("author_username") or ""), str(comment.get("author_name") or ""),
                    str(comment.get("text") or ""), str(comment.get("time_label") or ""),
                    str(comment.get("created_at") or utc_now_iso()), legacy_source, role, topic_id,
                ),
            )
            if not cursor.rowcount:
                raise ValueError("目标讨论帖不存在")
            conn.execute("UPDATE forum_replies SET status = ? WHERE id = ?", (status, reply_id))
        conn.execute(f"UPDATE {source_table} SET status = 'migrated' WHERE id = ?", (comment["id"],))
    return int(not existing)
