"""Converge legacy work comments into their permanent discussion topics."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import services as S
from backend.resource_discussions import ensure_topic
from ops.legacy_comments import copy_comment
from ops.postgres_maintenance import backup_before_change, is_transaction_conflict, maintenance_parser, maintenance_transaction, savepoint


def plan(conn) -> list[dict]:
    seed_comments = S.seed_ids("work_comments")
    rows = conn.execute("""
        SELECT c.*, COALESCE(m.topic_id, t.id) AS migration_topic_id
        FROM work_comments AS c
        LEFT JOIN curation_resource_topics AS m ON m.kind = 'work' AND m.target_id = c.work_id
        LEFT JOIN forum_topics AS t ON t.work_id = c.work_id AND t.work_id <> '' AND m.topic_id IS NULL
        WHERE c.status <> 'migrated'
          AND NOT EXISTS (
              SELECT 1 FROM forum_replies AS r
              WHERE r.legacy_source <> '' AND r.legacy_source = 'work_comments:' || c.id
          )
        ORDER BY c.created_at, c.id
    """)
    return [
        {
            "workId": str(row["work_id"]), "topicId": row["migration_topic_id"],
            "comment": dict(row), "legacySource": f"work_comments:{row['id']}",
        }
        for row in rows if str(row["id"]) not in seed_comments
    ]


def apply(conn, todo: list[dict]) -> tuple[int, list[str]]:
    copied = 0
    failures: list[str] = []
    failed_works: set[str] = set()
    mapped: dict[str, str] = {}

    for item in todo:
        work_id = item["workId"]
        topic_id = item.get("topicId") or mapped.get(work_id)
        try:
            if work_id not in mapped:
                with savepoint(conn):
                    if not topic_id:
                        work = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
                        if not work:
                            raise ValueError(f"找不到作品记录：{work_id}")
                        topic_id = ensure_topic(conn, "work", work_id, dict(work), initial_origin="legacy")
                    conn.execute("""
                        INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                        SELECT 'work', ?, id, 'legacy', ? FROM forum_topics WHERE id = ?
                        ON CONFLICT (kind, target_id) DO NOTHING
                    """, (work_id, S.utc_now_iso(), topic_id))
                mapped[work_id] = topic_id
            copied += copy_comment(conn, "work_comments", item, topic_id)
        except Exception as exc:
            if is_transaction_conflict(exc):
                raise
            failed_works.add(work_id)
            failures.append(f"{item['legacySource']}: {exc}")

    for work_id in mapped.keys() - failed_works:
        conn.execute(
            "UPDATE curation_resource_topics SET origin = 'submission' WHERE kind = 'work' AND target_id = ?",
            (work_id,),
        )
    return copied, failures


def main(argv: list[str] | None = None) -> int:
    parser = maintenance_parser("Copy legacy work comments into forum replies.")
    args = parser.parse_args(argv)
    with maintenance_transaction(parser, write=args.apply) as (conn, dsn):
        todo = plan(conn)
        print(f"待迁移评论：{len(todo)} 条")
        for work_id, count in sorted(Counter(item["workId"] for item in todo).items())[:10]:
            print(f"  {work_id}: {count}")
        if not args.apply:
            print("检查完成。加 --apply 执行。")
            return 0
        if not todo:
            print("没有需要迁移的评论。")
            return 0
        backup = backup_before_change(conn, dsn, args.backup_dir, "work-comments-before")
        print(f"已备份并通过验证：{backup}")
        copied, failures = apply(conn, todo)
    print(f"已迁移 {copied} 条。")
    for failure in failures:
        print(failure, file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
