"""Recompute cached social counters from their fact tables.

``works.likes``/``favorites``/``cheers``/``forks`` and ``forum_topics.likes``/
``favorites`` are caches.  The facts live in ``interactions``, ``collections``
and ``work_forks``.  Any historical drift (a cheer that used to bump likes, a
seeded baseline, a manual edit) is repaired by re-deriving the cache.

Usage:
    python -X utf8 ops/reconcile_social_counters.py --db .local/handraw_v2.db
    python -X utf8 ops/reconcile_social_counters.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def compute(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    works = conn.execute(
        """
        SELECT w.id,
               w.likes   AS cached_likes,
               w.favorites AS cached_favorites,
               w.cheers  AS cached_cheers,
               w.forks   AS cached_forks,
               (SELECT COUNT(*) FROM interactions i
                 WHERE i.target_type = 'like_work' AND i.target_id = w.id AND i.stamp_label = '') AS true_likes,
               (SELECT COUNT(*) FROM collections c
                 WHERE c.bucket = 'works' AND c.target_id = w.id) AS true_favorites,
               (SELECT COUNT(*) FROM interactions i
                 WHERE i.target_type = 'work' AND i.target_id = w.id) AS true_cheers,
               (SELECT COUNT(*) FROM work_forks f WHERE f.work_id = w.id) AS true_forks
          FROM works w
        """
    ).fetchall()

    topics = conn.execute(
        """
        SELECT t.id,
               t.likes AS cached_likes,
               t.favorites AS cached_favorites,
               (SELECT COUNT(*) FROM interactions i
                 WHERE i.target_type = 'like_topic' AND i.target_id = t.id AND i.stamp_label = '') AS true_likes,
               (SELECT COUNT(*) FROM collections c
                 WHERE c.bucket = 'topics' AND c.target_id = t.id) AS true_favorites
          FROM forum_topics t
        """
    ).fetchall()

    drift_works = [
        dict(row)
        for row in works
        if int(row["cached_likes"]) != int(row["true_likes"])
        or int(row["cached_favorites"]) != int(row["true_favorites"])
        or int(row["cached_cheers"]) != int(row["true_cheers"])
        or int(row["cached_forks"]) != int(row["true_forks"])
    ]
    drift_topics = [
        dict(row)
        for row in topics
        if int(row["cached_likes"]) != int(row["true_likes"])
        or int(row["cached_favorites"]) != int(row["true_favorites"])
    ]
    return {"works": drift_works, "topics": drift_topics}


def apply(conn: sqlite3.Connection, drift: dict[str, list[dict]]) -> None:
    for row in drift["works"]:
        conn.execute(
            "UPDATE works SET likes = ?, favorites = ?, cheers = ?, forks = ? WHERE id = ?",
            (row["true_likes"], row["true_favorites"], row["true_cheers"], row["true_forks"], row["id"]),
        )
    for row in drift["topics"]:
        conn.execute(
            "UPDATE forum_topics SET likes = ?, favorites = ? WHERE id = ?",
            (row["true_likes"], row["true_favorites"], row["id"]),
        )
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute social counters from fact tables.")
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 2

    conn = _connect(db_path)
    try:
        drift = compute(conn)
        print(f"作品计数不一致：{len(drift['works'])} 件")
        for row in drift["works"][:10]:
            print(
                f"  {row['id']}: likes {row['cached_likes']}→{row['true_likes']}, "
                f"favorites {row['cached_favorites']}→{row['true_favorites']}, "
                f"cheers {row['cached_cheers']}→{row['true_cheers']}, "
                f"forks {row['cached_forks']}→{row['true_forks']}"
            )
        print(f"帖子计数不一致：{len(drift['topics'])} 条")
        for row in drift["topics"][:10]:
            print(
                f"  {row['id']}: likes {row['cached_likes']}→{row['true_likes']}, "
                f"favorites {row['cached_favorites']}→{row['true_favorites']}"
            )

        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0
        if not drift["works"] and not drift["topics"]:
            print("无需修复。")
            return 0

        backup = db_path.with_name(db_path.name + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(db_path, backup)
        print(f"已备份：{backup}")
        apply(conn, drift)
        print("计数已按事实表重算。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
