"""Converge legacy asset comments into each asset's discussion topic.

After the change every official and community asset reads its comments from
``forum_replies`` through the ``origin='submission'`` mapping. Older assets
still keep their comments in ``asset_comments``; this script copies them across
once, using ``forum_replies.legacy_source`` to stay idempotent, then flips the
mapping so the reader path is unified.

Comments are inserted with ``status='migrating'`` and only afterwards updated to
their real status, because the notification trigger fires only on
``INSERT ... status='published'``. Without that step the migration would
re-notify every author about historical comments.

部署顺序：
1. 暂停写入，执行 SQLite WAL 备份并校验。
2. 运行 python ops/converge_asset_comments.py --apply 迁移旧评论（含旧作品评论反查迁移；未映射资源先建 legacy/official 映射，迁移完成翻转为 submission）。
3. 运行 python ops/ensure_resource_topics.py --apply（规范化小写映射，并为剩余无评论的 catalog 资源建立占位帖与 submission 映射）。
4. 启用新代码并恢复写入，执行接口验收。
注意：必须在暂停写入期间执行迁移，不能在上线新代码后再跑脚本。

Usage (dry run first, always):
    python -X utf8 ops/converge_asset_comments.py --db .local/handraw_v2.db
    python -X utf8 ops/converge_asset_comments.py --db .local/handraw_v2.db --apply
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
from backend.resource_discussions import resolve_resource
from ops import converge_work_comments


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def backup(conn: sqlite3.Connection, db_path: Path) -> Path:
    """Copy the database through SQLite's backup API and verify integrity."""
    target = db_path.with_name(db_path.name + f".bak-assets-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
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


def plan(conn: sqlite3.Connection) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """Return (asset_todo, unmapped_resources, work_todo, skipped_seeds). Starts from unmigrated comments (K2, K3)."""
    seed_ac = S.seed_ids("asset_comments")
    skipped_seeds: list[str] = []

    # 1. Unmigrated comments from asset_comments
    all_comments = conn.execute(
        """
        SELECT ac.* FROM asset_comments ac
        WHERE ac.status <> 'migrated'
          AND NOT EXISTS (
              SELECT 1 FROM forum_replies fr WHERE fr.legacy_source = 'asset_comments:' || ac.id
          )
        ORDER BY ac.created_at ASC
        """
    ).fetchall()

    asset_todo: list[dict] = []
    unmapped_dict: dict[tuple[str, str], dict] = {}

    for c in all_comments:
        cid = str(c["id"])
        if cid in seed_ac:
            skipped_seeds.append(cid)
            continue

        akind = str(c["asset_kind"])
        acode = str(c["asset_code"]).strip().upper().lstrip("#")
        source = f"asset_comments:{cid}"

        # Case-insensitive mapping lookup (K4)
        mapping = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = ? AND UPPER(target_id) = ?",
            (akind, acode),
        ).fetchone()

        topic_id = str(mapping["topic_id"]) if mapping else None
        if not topic_id and (akind, acode) not in unmapped_dict:
            res = resolve_resource(conn, akind, acode)
            if res:
                unmapped_dict[(akind, acode)] = res
            else:
                print(f"找不到未映射资源，跳过对应评论：kind={akind}, code={acode}, id={cid}", file=sys.stderr)
                continue

        asset_todo.append({
            "kind": akind,
            "targetId": acode,
            "topicId": topic_id,
            "comment": dict(c),
            "legacySource": source,
            "resource": unmapped_dict.get((akind, acode)),
        })

    unmapped_resources = [
        {"kind": k, "target_id": t, "resource": r}
        for (k, t), r in unmapped_dict.items()
    ]

    # 2. Work comments (K3)
    work_todo = converge_work_comments.plan(conn)

    return asset_todo, unmapped_resources, work_todo, skipped_seeds


def apply(
    conn: sqlite3.Connection,
    asset_todo: list[dict],
    unmapped_resources: list[dict],
    work_todo: list[dict],
) -> tuple[int, list[str]]:
    now = _now()
    copied = 0
    failures: list[str] = []
    asset_failures: dict[tuple[str, str], list[str]] = {}
    asset_counts: dict[tuple[str, str], int] = {}

    # Ensure topics for unmapped resources with origin='official' before migration (K5/L3)
    from backend.resource_discussions import ensure_topic
    created_topics: dict[tuple[str, str], str] = {}
    for item in unmapped_resources:
        try:
            akind = item["kind"]
            atarget = item["target_id"]
            res = item["resource"]
            tid = ensure_topic(conn, akind, atarget, res, initial_origin="official")
            created_topics[(akind, atarget)] = tid
        except Exception as e:
            err = f"为未映射资源创建讨论帖失败：{item['kind']} {item['target_id']}: {e}"
            failures.append(err)
            print(err, file=sys.stderr)

    for item in asset_todo:
        akind = item["kind"]
        atarget = item["targetId"]
        key = (akind, atarget)
        asset_counts[key] = asset_counts.get(key, 0) + 1

        topic_id = item.get("topicId") or created_topics.get(key)
        if not topic_id:
            row = conn.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind = ? AND UPPER(target_id) = ?",
                (akind, atarget),
            ).fetchone()
            if row:
                topic_id = str(row["topic_id"])

        if not topic_id:
            err = f"缺少目标讨论帖，跳过评论：{item['legacySource']}"
            failures.append(err)
            asset_failures.setdefault(key, []).append(err)
            continue

        already = conn.execute(
            "SELECT 1 FROM forum_replies WHERE legacy_source = ?", (item["legacySource"],)
        ).fetchone()
        if already:
            conn.execute("UPDATE asset_comments SET status = 'migrated' WHERE id = ?", (item["comment"]["id"],))
            continue

        comment = item["comment"]
        reply_id = f"reply_{uuid.uuid4().hex[:16]}"
        st = str(comment.get("status") or "published")
        actor_role = comment.get("status_actor_role")
        if not actor_role and st == "hidden":
            actor_role = "admin"
        else:
            actor_role = str(actor_role or "")

        conn.execute("SAVEPOINT copy_asset_comment")
        try:
            conn.execute(
                """
                INSERT INTO forum_replies (
                    id, topic_id, author_username, author_name, text,
                    mounted_style, mounted_layout, likes, accepted, status, time_label, created_at, legacy_source, status_actor_role
                ) VALUES (?, ?, ?, ?, ?, '', '', 0, 0, 'migrating', ?, ?, ?, ?)
                """,
                (
                    reply_id,
                    topic_id,
                    str(comment.get("author_username") or ""),
                    str(comment.get("author_name") or ""),
                    str(comment.get("text") or ""),
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
            # K2: Update old record status to 'migrated' in same SAVEPOINT
            conn.execute(
                "UPDATE asset_comments SET status = 'migrated' WHERE id = ?",
                (comment["id"],),
            )
            conn.execute("RELEASE SAVEPOINT copy_asset_comment")
            copied += 1
        except Exception as e:
            conn.execute("ROLLBACK TO SAVEPOINT copy_asset_comment")
            err = f"复制评论失败：{item['legacySource']}: {e}"
            failures.append(err)
            asset_failures.setdefault(key, []).append(err)

    # Flip asset mappings ONLY for assets whose comments had 0 failures
    for (akind, atarget) in asset_counts:
        if (akind, atarget) not in asset_failures:
            conn.execute(
                "UPDATE curation_resource_topics SET origin = 'submission' WHERE kind = ? AND UPPER(target_id) = ?",
                (akind, atarget),
            )

    # Process legacy works (K3)
    if work_todo:
        w_copied, w_failures = converge_work_comments.apply(conn, work_todo)
        copied += w_copied
        failures.extend(w_failures)

    conn.commit()
    return copied, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy legacy asset comments into forum replies.")
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 2

    conn = _connect(db_path)
    try:
        asset_todo, unmapped_resources, work_todo, skipped_seeds = plan(conn)
        total_todo = len(asset_todo) + len(work_todo)
        print(f"待迁移评论：{total_todo} 条 (资源评论 {len(asset_todo)} 条，作品评论 {len(work_todo)} 条)")
        if skipped_seeds:
            print(f"跳过演示评论：{len(skipped_seeds)} 条")

        if asset_todo:
            by_asset: dict[str, int] = {}
            for item in asset_todo:
                key = f"{item['kind']}:{item['targetId']}"
                by_asset[key] = by_asset.get(key, 0) + 1
            for target_key, count in sorted(by_asset.items())[:10]:
                print(f"  {target_key}: {count}")
            if len(by_asset) > 10:
                print(f"  ... 另有 {len(by_asset) - 10} 项资源")

        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0

        bak_path = backup(conn, db_path)
        print(f"已备份并通过验证：{bak_path}")
        copied, failures = apply(conn, asset_todo, unmapped_resources, work_todo)
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
