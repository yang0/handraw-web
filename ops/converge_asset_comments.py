"""Converge legacy asset and work comments into permanent discussions."""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import services as S
from backend.resource_discussions import ensure_topic, resolve_resource
from ops import converge_work_comments
from ops.legacy_comments import copy_comment
from ops.postgres_maintenance import backup_before_change, is_transaction_conflict, maintenance_parser, maintenance_transaction, savepoint


def plan(conn) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    seed_comments = S.seed_ids("asset_comments")
    mappings = {}
    for row in conn.execute("""
        SELECT kind, UPPER(target_id) AS normalized_id, topic_id
        FROM curation_resource_topics
        WHERE kind IN ('style', 'layout')
        ORDER BY CASE WHEN target_id = UPPER(target_id) THEN 0 ELSE 1 END, target_id, topic_id
    """):
        mappings.setdefault((row["kind"], row["normalized_id"]), row["topic_id"])

    pending: list[dict] = []
    skipped: list[str] = []
    unresolved: dict[tuple[str, str], dict | None] = {}
    for row in conn.execute("""
        SELECT c.* FROM asset_comments AS c
        WHERE c.status <> 'migrated'
          AND NOT EXISTS (
              SELECT 1 FROM forum_replies AS r
              WHERE r.legacy_source <> '' AND r.legacy_source = 'asset_comments:' || c.id
          )
        ORDER BY c.created_at, c.id
    """):
        comment_id = str(row["id"])
        if comment_id in seed_comments:
            skipped.append(comment_id)
            continue
        kind = str(row["asset_kind"])
        code = str(row["asset_code"]).strip().upper().lstrip("#")
        key = (kind, code)
        topic_id = mappings.get(key)
        if not topic_id:
            if key not in unresolved:
                unresolved[key] = resolve_resource(conn, kind, code)
            if not unresolved[key]:
                print(f"找不到未映射资源，跳过对应评论：kind={kind}, code={code}, id={comment_id}", file=sys.stderr)
                continue
        pending.append({
            "kind": kind, "targetId": code, "topicId": topic_id, "comment": dict(row),
            "legacySource": f"asset_comments:{comment_id}", "resource": unresolved.get(key),
        })

    unmapped = [
        {"kind": kind, "target_id": code, "resource": resource}
        for (kind, code), resource in unresolved.items() if resource
    ]
    return pending, unmapped, converge_work_comments.plan(conn), skipped


def apply(conn, asset_todo: list[dict], unmapped_resources: list[dict], work_todo: list[dict]) -> tuple[int, list[str]]:
    copied = 0
    failures: list[str] = []
    failed_assets: set[tuple[str, str]] = set()
    successful: dict[tuple[str, str], str] = {}
    created_topics: dict[tuple[str, str], str] = {}
    for item in unmapped_resources:
        key = (item["kind"], item["target_id"])
        try:
            with savepoint(conn):
                created_topics[key] = ensure_topic(conn, *key, item["resource"], initial_origin="official")
        except Exception as exc:
            if is_transaction_conflict(exc):
                raise
            failed_assets.add(key)
            failures.append(f"为未映射资源创建讨论帖失败：{key[0]} {key[1]}: {exc}")

    for item in asset_todo:
        key = (item["kind"], item["targetId"])
        topic_id = item.get("topicId") or created_topics.get(key)
        try:
            if not topic_id:
                raise ValueError("缺少目标讨论帖")
            copied += copy_comment(conn, "asset_comments", item, topic_id)
            successful[key] = topic_id
        except Exception as exc:
            if is_transaction_conflict(exc):
                raise
            failed_assets.add(key)
            failures.append(f"{item['legacySource']}: {exc}")

    for key in successful.keys() - failed_assets:
        conn.execute(
            """UPDATE curation_resource_topics SET origin = 'submission'
               WHERE kind = ? AND UPPER(target_id) = ? AND topic_id = ?""",
            (*key, successful[key]),
        )

    if work_todo:
        work_copied, work_failures = converge_work_comments.apply(conn, work_todo)
        copied += work_copied
        failures.extend(work_failures)
    return copied, failures


def main(argv: list[str] | None = None) -> int:
    parser = maintenance_parser("Copy legacy asset and work comments into forum replies.")
    args = parser.parse_args(argv)
    with maintenance_transaction(parser, write=args.apply) as (conn, dsn):
        asset_todo, unmapped, work_todo, skipped = plan(conn)
        print(f"待迁移评论：资源 {len(asset_todo)} 条，作品 {len(work_todo)} 条，跳过演示评论 {len(skipped)} 条")
        if not args.apply:
            print("检查完成。加 --apply 执行。")
            return 0
        if not asset_todo and not work_todo:
            print("没有需要迁移的评论。")
            return 0
        backup = backup_before_change(conn, dsn, args.backup_dir, "asset-comments-before")
        print(f"已备份并通过验证：{backup}")
        copied, failures = apply(conn, asset_todo, unmapped, work_todo)
    print(f"已迁移 {copied} 条。")
    for failure in failures:
        print(failure, file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
