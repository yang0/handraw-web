"""Remove fork facts that were written by the publish path.

Before this fix, publishing a work with ``forkOf`` inserted a ``work_forks``
row immediately, so five throwaway accounts plus one reconcile run became five
"real" forks.  A legitimate fork row always carries the generation that produced
it; rows with an empty ``first_generation_id`` can only come from the publish
path.

Usage:
    python -X utf8 ops/purge_publish_time_forks.py --db .local/handraw_v2.db
    python -X utf8 ops/purge_publish_time_forks.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def plan(conn: sqlite3.Connection) -> list[dict]:
    """Rows that cannot be backed by a real generation.

    A legitimate fork points at the generation that produced it.  Rows are
    suspicious when they have no generation at all, or when the named generation
    does not exist / did not succeed.
    """
    rows = conn.execute(
        """
        SELECT f.work_id, f.user_id, f.first_generation_id, f.created_at
          FROM work_forks f
         WHERE f.first_generation_id = ''
            OR NOT EXISTS (
                 SELECT 1 FROM studio_generations g
                  WHERE g.id = f.first_generation_id
                    AND g.status = 'success'
                    AND COALESCE(g.engine, '') <> 'sample'
               )
        """
    ).fetchall()
    return [dict(r) for r in rows]


def apply(conn: sqlite3.Connection, todo: list[dict]) -> int:
    for row in todo:
        conn.execute(
            "DELETE FROM work_forks WHERE work_id = ? AND user_id = ?",
            (row["work_id"], row["user_id"]),
        )
    # Recompute every work's cached counter from the remaining facts.
    conn.execute(
        """UPDATE works SET forks = (
               SELECT COUNT(*) FROM work_forks f WHERE f.work_id = works.id
           )"""
    )
    conn.commit()
    return len(todo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Purge fork facts created by publishing.")
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        todo = plan(conn)
        print(f"待清理的可疑复刻记录：{len(todo)} 条（无生成来源）")
        for row in todo[:10]:
            print(f"  {row['work_id']} <- user {row['user_id']}")
        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0
        if not todo:
            print("无需清理。")
            return 0
        backup = db_path.with_name(db_path.name + f".bak-forks-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(db_path, backup)
        print(f"已备份：{backup}")
        removed = apply(conn, todo)
        print(f"已删除 {removed} 条，并按事实表重算了 works.forks。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
