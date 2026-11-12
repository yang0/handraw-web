"""Create missing canonical resource discussions and normalize unambiguous mappings."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.resource_discussions import ensure_topic, static_catalog
from ops.postgres_maintenance import backup_before_change, maintenance_parser, maintenance_transaction


_NORMALIZABLE_MAPPINGS = """
    SELECT kind, MIN(target_id) AS target_id, UPPER(target_id) AS norm_id
    FROM curation_resource_topics
    WHERE kind IN ('style', 'layout')
    GROUP BY kind, UPPER(target_id)
    HAVING COUNT(*) = 1 AND MIN(target_id) <> UPPER(target_id)
"""


def find_case_duplicates(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT kind, UPPER(target_id) AS norm_id, COUNT(*) AS cnt,
               STRING_AGG(target_id, ', ' ORDER BY target_id) AS targets
        FROM curation_resource_topics
        WHERE kind IN ('style', 'layout')
        GROUP BY kind, UPPER(target_id)
        HAVING COUNT(*) > 1
    """)
    return [dict(row) for row in rows]


def find_normalizable_mappings(conn) -> list[dict]:
    return [dict(row) for row in conn.execute(_NORMALIZABLE_MAPPINGS)]


def find_affected_exclusive_mappings(conn) -> int:
    return int(conn.execute("""
        SELECT COUNT(*)
        FROM curation_resource_topics AS m
        JOIN catalog_assets AS a ON UPPER(a.code) = UPPER(m.target_id) AND a.kind = m.kind
        JOIN forum_topics AS t ON t.id = m.topic_id
        WHERE a.source_type = 'exclusive' AND TRIM(COALESCE(t.author_username, '')) <> ''
    """).fetchone()[0])


def plan(conn) -> tuple[list[tuple[str, str, dict]], list[tuple[str, str, dict]]]:
    seen = {
        (row["kind"], row["normalized_id"])
        for row in conn.execute("""
            SELECT kind, UPPER(target_id) AS normalized_id FROM curation_resource_topics
            WHERE kind IN ('style', 'layout')
        """)
    }
    needed_assets: list[tuple[str, str, dict]] = []
    for code, item in static_catalog().items():
        kind = str(item.get("kind") or "style")
        key = (kind, code.strip().upper().lstrip("#"))
        if kind in ("style", "layout") and key not in seen:
            seen.add(key)
            needed_assets.append((*key, item))

    for row in conn.execute("""
        SELECT code, kind, source_type, name, description, image_url, author_username, author_name
        FROM catalog_assets WHERE status = 'published' AND kind IN ('style', 'layout')
        ORDER BY code
    """):
        key = (row["kind"], str(row["code"]).strip().upper().lstrip("#"))
        if key[1] and key not in seen:
            seen.add(key)
            needed_assets.append((*key, dict(row)))

    needed_works = [
        ("work", str(row["id"]), dict(row)) for row in conn.execute("""
            SELECT w.id, w.title, w.author_username, w.author_name, w.notes, w.status, w.images_json
            FROM works AS w
            WHERE w.status = 'published' AND NOT EXISTS (
                SELECT 1 FROM curation_resource_topics AS m WHERE m.kind = 'work' AND m.target_id = w.id
            )
            ORDER BY w.id
        """)
    ]
    return needed_assets, needed_works


def apply(conn, needed_assets: list[tuple[str, str, dict]], needed_works: list[tuple[str, str, dict]]) -> tuple[int, list[str]]:
    conn.execute(f"""
        UPDATE curation_resource_topics SET target_id = UPPER(target_id)
        WHERE (kind, target_id) IN (SELECT kind, target_id FROM ({_NORMALIZABLE_MAPPINGS}) AS singleton)
    """)
    topic_ids = [
        ensure_topic(conn, kind, code, resource, initial_origin="submission")
        for kind, code, resource in needed_assets
    ]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for kind, work_id, resource in needed_works:
        topic_id = ensure_topic(conn, kind, work_id, resource, initial_origin="submission", listed_at_ms=None)
        conn.execute("""
            INSERT INTO audit_logs (
                actor_id, actor_username, actor_role, action, target_type, target_id,
                reason, details_json, created_at
            ) VALUES (NULL, 'system', 'system', 'work.prebuild_unlisted_topic', 'topic', ?, ?, ?, ?)
        """, (
            topic_id, f"Prebuilt unlisted topic {topic_id} for work {work_id}",
            json.dumps({"work_id": work_id, "topic_id": topic_id}), now,
        ))
        topic_ids.append(topic_id)
    return len(topic_ids), topic_ids


def write_manifest(path: Path, topic_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "created_count": len(topic_ids),
        "topic_ids": topic_ids,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = maintenance_parser("Ensure discussion topics exist for catalog resources and works.")
    parser.add_argument("--manifest", type=Path, help="Path to write the topic manifest after commit")
    args = parser.parse_args(argv)

    topic_ids: list[str] = []
    with maintenance_transaction(parser, write=args.apply) as (conn, dsn):
        duplicates = find_case_duplicates(conn)
        for row in duplicates:
            print(f"重复映射，需人工核查：{row['kind']} {row['norm_id']} [{row['targets']}]")
        needed_assets, needed_works = plan(conn)
        normalized = find_normalizable_mappings(conn)
        print(f"待建讨论帖：资源 {len(needed_assets)} 个，作品 {len(needed_works)} 个，待规范化映射 {len(normalized)} 个")
        print(f"历史受影响的 exclusive 映射数：{find_affected_exclusive_mappings(conn)} 个")
        if not args.apply:
            print("检查完成。加 --apply 执行。")
            return 0
        if needed_assets or needed_works or normalized:
            backup = backup_before_change(conn, dsn, args.backup_dir, "resource-topics-before")
            print(f"已备份并通过验证：{backup}")
            _, topic_ids = apply(conn, needed_assets, needed_works)

    if args.manifest:
        write_manifest(args.manifest, topic_ids)
    print(f"已为 {len(topic_ids)} 个资源建立讨论映射。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
