"""Ensure discussion topics and submission mappings exist for all resources.

Every official style and layout in ``catalog.json`` as well as every published
work must have a permanent discussion topic in ``forum_topics`` mapped via
``curation_resource_topics`` with ``origin='submission'``. This allows direct
canonical addressing (e.g. ``/t/FB-041``) without requiring a first comment.

Usage (dry run first, always):
    python -X utf8 ops/ensure_resource_topics.py --db .local/handraw_v2.db
    python -X utf8 ops/ensure_resource_topics.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.resource_discussions import ensure_topic, static_catalog


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def backup(conn: sqlite3.Connection, db_path: Path) -> Path:
    """Copy the database through SQLite's backup API and verify integrity."""
    target = db_path.with_name(db_path.name + f".bak-topics-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
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


def find_case_duplicates(conn: sqlite3.Connection) -> list[dict]:
    """Find mappings with same code but different case (report only)."""
    rows = conn.execute(
        """
        SELECT kind, UPPER(target_id) AS norm_id, COUNT(*) AS cnt, GROUP_CONCAT(target_id, ', ') AS targets
        FROM curation_resource_topics
        WHERE kind IN ('style', 'layout')
        GROUP BY kind, UPPER(target_id)
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    return [dict(r) for r in rows]


def find_normalizable_mappings(conn: sqlite3.Connection) -> list[dict]:
    """Find single lowercase mappings that can be safely normalized to uppercase."""
    rows = conn.execute(
        """
        SELECT kind, target_id, UPPER(target_id) AS norm_id
        FROM curation_resource_topics
        WHERE kind IN ('style', 'layout')
          AND target_id <> UPPER(target_id)
          AND NOT EXISTS (
              SELECT 1 FROM curation_resource_topics m2
              WHERE m2.kind = curation_resource_topics.kind
                AND m2.target_id = UPPER(curation_resource_topics.target_id)
          )
        """
    ).fetchall()
    return [dict(r) for r in rows]


def plan(conn: sqlite3.Connection) -> tuple[list[tuple[str, str, dict]], list[tuple[str, str, dict]]]:
    """Return (needed_assets, needed_works)."""
    # 1. Official styles & layouts from catalog.json
    catalog = static_catalog()
    needed_assets: list[tuple[str, str, dict]] = []
    for code, item in catalog.items():
        kind = str(item.get("kind") or "style")
        if kind not in ("style", "layout"):
            continue
        norm_code = code.strip().upper().lstrip("#")
        row = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = ? AND UPPER(target_id) = ?",
            (kind, norm_code),
        ).fetchone()
        if not row:
            needed_assets.append((kind, norm_code, item))

    # 1b. Published styles & layouts from catalog_assets (exclusive, community, etc.)
    db_assets = conn.execute(
        """
        SELECT * FROM catalog_assets
        WHERE status = 'published' AND kind IN ('style', 'layout')
        """
    ).fetchall()
    for row in db_assets:
        item = dict(row)
        kind = str(item.get("kind") or "style")
        norm_code = str(item.get("code") or "").strip().upper().lstrip("#")
        if not norm_code:
            continue
        if any(a[0] == kind and a[1] == norm_code for a in needed_assets):
            continue
        exists = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = ? AND UPPER(target_id) = ?",
            (kind, norm_code),
        ).fetchone()
        if not exists:
            needed_assets.append((kind, norm_code, item))

    # 2. Published works without mapping
    needed_works: list[tuple[str, str, dict]] = []
    works = conn.execute(
        """
        SELECT w.* FROM works w
        WHERE w.status = 'published'
          AND NOT EXISTS (
              SELECT 1 FROM curation_resource_topics m
              WHERE m.kind = 'work' AND m.target_id = w.id
          )
        """
    ).fetchall()
    for work in works:
        needed_works.append(("work", str(work["id"]), dict(work)))

    return needed_assets, needed_works


def apply(
    conn: sqlite3.Connection,
    needed_assets: list[tuple[str, str, dict]],
    needed_works: list[tuple[str, str, dict]],
) -> int:
    # Normalize single lowercase mappings to uppercase where no uppercase mapping exists yet
    conn.execute(
        """
        UPDATE curation_resource_topics
        SET target_id = UPPER(target_id)
        WHERE kind IN ('style', 'layout')
          AND target_id <> UPPER(target_id)
          AND NOT EXISTS (
              SELECT 1 FROM curation_resource_topics m2
              WHERE m2.kind = curation_resource_topics.kind
                AND m2.target_id = UPPER(curation_resource_topics.target_id)
          )
        """
    )

    created = 0
    for kind, target_id, res in needed_assets:
        ensure_topic(conn, kind, target_id, res, initial_origin="submission")
        created += 1

    for kind, target_id, res in needed_works:
        ensure_topic(conn, kind, target_id, res, initial_origin="submission")
        created += 1

    conn.commit()
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ensure discussion topics exist for all catalog resources and works.")
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 2

    conn = _connect(db_path)
    try:
        dup_cases = find_case_duplicates(conn)
        if dup_cases:
            print("发现大小写不同的重复映射（需人工核查，不自动合并）：")
            for d in dup_cases:
                print(f"  {d['kind']} {d['norm_id']}: [{d['targets']}]")

        needed_assets, needed_works = plan(conn)
        norm_mappings = find_normalizable_mappings(conn)
        total_needed = len(needed_assets) + len(needed_works) + len(norm_mappings)
        print(
            f"待建讨论帖：资源 {len(needed_assets)} 个，作品 {len(needed_works)} 个，待规范化大小写映射 {len(norm_mappings)} 个 (共 {total_needed} 个)"
        )

        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0
        if total_needed == 0 and not dup_cases:
            print("所有资源均已建立讨论帖子且映射规范，无需更新。")
            return 0

        bak_path = backup(conn, db_path)
        print(f"已备份并通过验证：{bak_path}")
        created = apply(conn, needed_assets, needed_works)
        print(f"已为 {created} 个资源创建帖子与映射（单项小写映射已规范化为大写）。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
