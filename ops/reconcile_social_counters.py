"""Recompute work and topic counters from the PostgreSQL interaction records."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_storage_root
from ops.postgres_backup import dump_snapshot


_COUNTER_DRIFT_SQL = """
WITH interaction_counts AS (
    SELECT target_id,
           count(*) FILTER (WHERE target_type = 'like_work') AS work_likes,
           count(*) FILTER (WHERE target_type = 'like_topic') AS topic_likes,
           count(*) FILTER (WHERE target_type = 'work') AS cheers
    FROM public.interactions
    WHERE target_type = 'work'
       OR (target_type IN ('like_work', 'like_topic') AND stamp_label = '')
    GROUP BY target_id
), collection_counts AS (
    SELECT target_id,
           count(*) FILTER (WHERE bucket = 'works') AS work_favorites,
           count(*) FILTER (WHERE bucket = 'topics') AS topic_favorites
    FROM public.collections
    WHERE bucket IN ('works', 'topics')
    GROUP BY target_id
), fork_counts AS (
    SELECT work_id, count(*) AS forks FROM public.work_forks GROUP BY work_id
), work_counts AS (
    SELECT w.id, w.likes AS cached_likes, w.favorites AS cached_favorites,
           w.cheers AS cached_cheers, w.forks AS cached_forks,
           coalesce(i.work_likes, 0) AS true_likes,
           coalesce(c.work_favorites, 0) AS true_favorites,
           coalesce(i.cheers, 0) AS true_cheers,
           coalesce(f.forks, 0) AS true_forks
    FROM public.works AS w
    LEFT JOIN interaction_counts AS i ON i.target_id = w.id
    LEFT JOIN collection_counts AS c ON c.target_id = w.id
    LEFT JOIN fork_counts AS f ON f.work_id = w.id
), topic_counts AS (
    SELECT t.id, t.likes AS cached_likes, t.favorites AS cached_favorites,
           coalesce(i.topic_likes, 0) AS true_likes,
           coalesce(c.topic_favorites, 0) AS true_favorites
    FROM public.forum_topics AS t
    LEFT JOIN interaction_counts AS i ON i.target_id = t.id
    LEFT JOIN collection_counts AS c ON c.target_id = t.id
)
SELECT 'works' AS kind, work_counts.*
FROM work_counts
WHERE (cached_likes, cached_favorites, cached_cheers, cached_forks)
      IS DISTINCT FROM (true_likes, true_favorites, true_cheers, true_forks)
UNION ALL
SELECT 'topics', id, cached_likes, cached_favorites, NULL, NULL,
       true_likes, true_favorites, NULL, NULL
FROM topic_counts
WHERE (cached_likes, cached_favorites) IS DISTINCT FROM (true_likes, true_favorites)
ORDER BY kind, id
"""


def compute(conn) -> dict[str, list[dict]]:
    drift: dict[str, list[dict]] = {"works": [], "topics": []}
    for row in conn.execute(_COUNTER_DRIFT_SQL):
        drift[row["kind"]].append(row)
    return drift


def apply(conn, drift: dict[str, list[dict]]) -> None:
    works = drift["works"]
    if works:
        conn.execute(
            """
            UPDATE public.works AS w
            SET likes = d.likes, favorites = d.favorites, cheers = d.cheers, forks = d.forks
            FROM unnest(%s::text[], %s::bigint[], %s::bigint[], %s::bigint[], %s::bigint[])
                 AS d(id, likes, favorites, cheers, forks)
            WHERE w.id = d.id
            """,
            tuple([row[key] for row in works] for key in (
                "id", "true_likes", "true_favorites", "true_cheers", "true_forks",
            )),
        )
    topics = drift["topics"]
    if topics:
        conn.execute(
            """
            UPDATE public.forum_topics AS t SET likes = d.likes, favorites = d.favorites
            FROM unnest(%s::text[], %s::bigint[], %s::bigint[]) AS d(id, likes, favorites)
            WHERE t.id = d.id
            """,
            tuple([row[key] for row in topics] for key in ("id", "true_likes", "true_favorites")),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes after backup (default is a dry run)")
    parser.add_argument("--backup-dir", type=Path, default=get_storage_root() / "backups")
    args = parser.parse_args(argv)
    dsn = os.environ.get("HANDRAW_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("Set HANDRAW_DATABASE_URL to the target PostgreSQL database")

    import psycopg
    from psycopg.rows import dict_row

    repaired = False
    try:
        with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
            if args.apply:
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            else:
                conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL lock_timeout = '5s'")
            drift = compute(conn)
            for kind, label, columns in (
                ("works", "作品", ("likes", "favorites", "cheers", "forks")),
                ("topics", "帖子", ("likes", "favorites")),
            ):
                print(f"{label}计数不一致：{len(drift[kind])}")
                for row in drift[kind][:10]:
                    delta = ", ".join(f"{col} {row['cached_' + col]}→{row['true_' + col]}" for col in columns)
                    print(f"  {row['id']}: {delta}")
            if not args.apply:
                print("检查完成。加 --apply 执行修复。")
            elif any(drift.values()):
                snapshot = conn.execute("SELECT pg_export_snapshot() AS snapshot").fetchone()["snapshot"]
                backup = dump_snapshot(dsn, snapshot, args.backup_dir)
                print(f"已备份：{backup}")
                apply(conn, drift)
                repaired = True
            else:
                print("无需修复。")
    except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable):
        print("对账遇到并发修改或锁冲突，事务已回滚。请重新执行。", file=sys.stderr)
        return 1

    if repaired:
        from backend.home_scenarios import invalidate_scenarios_cache

        invalidate_scenarios_cache()
        print("计数已按事实表重算。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
