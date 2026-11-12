"""Remove fork facts without a successful generation for the same actor and work."""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.postgres_maintenance import backup_before_change, maintenance_parser, maintenance_transaction


def plan(conn) -> list[dict]:
    return [dict(row) for row in conn.execute("""
        SELECT f.work_id, f.user_id, f.first_generation_id, f.created_at
        FROM work_forks AS f
        WHERE f.first_generation_id = '' OR NOT EXISTS (
            SELECT 1 FROM studio_generations AS g
            WHERE g.id = f.first_generation_id AND g.status = 'success'
              AND COALESCE(g.engine, '') <> 'sample'
              AND g.user_id = f.user_id AND COALESCE(g.fork_work_id, '') = f.work_id
        )
        ORDER BY f.work_id, f.user_id
    """)]


def apply(conn, todo: list[dict]) -> int:
    removed = conn.executemany("""
        DELETE FROM work_forks
        WHERE work_id = ? AND user_id = ? AND first_generation_id = ? AND created_at = ?
    """, [
        (row["work_id"], row["user_id"], row["first_generation_id"], row["created_at"])
        for row in todo
    ]).rowcount
    if removed:
        conn.execute("""
            WITH fork_counts AS (
                SELECT work_id, COUNT(*) AS forks FROM work_forks GROUP BY work_id
            ), drift AS (
                SELECT w.id, COALESCE(f.forks, 0) AS forks
                FROM works AS w LEFT JOIN fork_counts AS f ON f.work_id = w.id
                WHERE w.forks <> COALESCE(f.forks, 0)
            )
            UPDATE works SET forks = drift.forks FROM drift WHERE works.id = drift.id
        """)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = maintenance_parser("Purge fork facts without a valid generation.")
    args = parser.parse_args(argv)
    with maintenance_transaction(parser, write=args.apply) as (conn, dsn):
        todo = plan(conn)
        print(f"待清理的可疑复刻记录：{len(todo)} 条")
        for row in todo[:10]:
            print(f"  {row['work_id']} <- user {row['user_id']}  gen={row['first_generation_id'] or '(none)'}")
        if not args.apply:
            print("检查完成。加 --apply 执行。")
            return 0
        if not todo:
            print("无需清理。")
            return 0
        backup = backup_before_change(conn, dsn, args.backup_dir, "fork-facts-before")
        print(f"已备份并通过验证：{backup}")
        removed = apply(conn, todo)
    print(f"已删除 {removed} 条，并按事实表修正复刻计数。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
