"""Additive cutover of current documents and unambiguous terminal executions."""

from __future__ import annotations

import json

from .db import utc_now_iso
from .generation_v3 import _stable_id, _upsert_media
from .studio_articles import sync_illustrations
from .studio_canvases import validate_canvas_document
from .studio_execution import lock_generation_actor
from .services import ServiceError


def _images(row):
    result = []
    values = json.loads(row["items_json"] or "[]")
    if not isinstance(values, list):
        raise ValueError("invalid_legacy_media")
    for item in values:
        if isinstance(item, dict) and item.get("status") in (
            "failed",
            "error",
            "cancelled",
            "refunded",
        ):
            continue
        value = (
            str(item.get("imageUrl") or item.get("url") or "")
            if isinstance(item, dict)
            else str(item or "")
        )
        value = value.strip().split("?", 1)[0]
        if value and value not in result:
            result.append(value)
    return result


def _media_owned(tx, uid, url):
    if not url:
        return True
    value = str(url).split("?", 1)[0]
    if (
        value.startswith("/images/")
        and ".." not in value.split("/")
        and "\\" not in value
    ):
        return True
    return bool(
        tx.execute(
            "SELECT 1 FROM media_assets WHERE owner_user_id=? AND storage_key=? "
            "UNION ALL SELECT 1 FROM user_uploads WHERE user_id=? AND image_url=? AND deleted_at IS NULL "
            "UNION ALL SELECT 1 FROM studio_generation_media WHERE user_id=? AND media_url=? LIMIT 1",
            (uid, value, uid, value, uid, value),
        ).fetchone()
    )


def upgrade_studio_data(db, *, apply=False, limit=1000):
    tx = db.get_conn()
    ready = tx.execute(
        "SELECT to_regclass('public.article_illustrations') IS NOT NULL"
    ).fetchone()[0]
    report = {
        "ok": True,
        "applied": apply,
        "schemaReady": bool(ready),
        "articles": 0,
        "runs": 0,
        "attempts": 0,
        "canvases": 0,
        "archivedWorkflows": 0,
        "issues": [],
    }
    if not ready:
        report["ok"] = False
        report["issues"].append({"reason": "apply_schema_118_before_backfill"})
        return report
    articles = tx.execute(
        "SELECT a.* FROM studio_articles a WHERE a.deleted_at='' AND NOT a.illustrations_ready ORDER BY a.id LIMIT ?",
        (limit,),
    ).fetchall()
    for article in articles:
        try:
            cards = json.loads(article["cards_json"])
            if (
                not isinstance(cards, list)
                or len(cards) > 200
                or not all(isinstance(c, dict) for c in cards)
            ):
                raise ValueError("invalid_legacy_cards")
            locals_ = [str(c.get("id") or f"card_{n}") for n, c in enumerate(cards)]
            if len(set(locals_)) != len(locals_) or any(
                len(key) > 160 for key in locals_
            ):
                raise ValueError("invalid_legacy_card_identity")
            generation_ids = [str(c["genId"]) for c in cards if c.get("genId")]
            if (
                generation_ids
                and tx.execute(
                    "SELECT 1 FROM studio_generations WHERE user_id=? AND id=ANY(?) AND status IN ('queued','running') LIMIT 1",
                    (article["user_id"], generation_ids),
                ).fetchone()
            ):
                raise ValueError("wait_for_inflight_article_generation")
            if not all(
                _media_owned(tx, article["user_id"], card.get("imageUrl"))
                for card in cards
            ):
                raise ValueError("unresolved_legacy_media_owner")
            if apply:
                with db.transaction() as write:
                    write.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(?,208))",
                        (article["id"],),
                    )
                    current = write.execute(
                        "SELECT * FROM studio_articles WHERE id=? FOR UPDATE",
                        (article["id"],),
                    ).fetchone()
                    if (
                        current["cards_json"] != article["cards_json"]
                        or current["updated_at_ms"] != article["updated_at_ms"]
                    ):
                        raise ValueError("document_changed_during_upgrade")
                    if write.execute(
                        "SELECT 1 FROM article_illustrations WHERE article_id=? LIMIT 1",
                        (article["id"],),
                    ).fetchone():
                        continue
                    sync_illustrations(write, article["user_id"], article["id"], cards)
                    settings = dict(current["settings_json"])
                    for role, key in (
                        ("cover", "coverRatio"),
                        ("inline", "inlineRatio"),
                    ):
                        ratio = next(
                            (
                                c.get("ratio")
                                for c in cards
                                if c.get("role") == role and c.get("ratio")
                            ),
                            None,
                        )
                        if ratio:
                            settings.setdefault(key, ratio)
                    write.execute(
                        "UPDATE studio_articles SET write_seq=GREATEST(write_seq,1),illustrations_ready=true,settings_json=?::jsonb WHERE id=?",
                        (json.dumps(settings), article["id"]),
                    )
            report["articles"] += 1
        except (ValueError, TypeError) as exc:
            reasons = {
                "invalid_legacy_cards",
                "invalid_legacy_card_identity",
                "wait_for_inflight_article_generation",
                "unresolved_legacy_media_owner",
                "document_changed_during_upgrade",
            }
            report["issues"].append(
                {
                    "articleId": article["id"],
                    "reason": str(exc)
                    if str(exc) in reasons
                    else "legacy_article_requires_review",
                }
            )
    # A legacy graph remains an exportable archive. Already-native parameter
    # documents can be copied without guessing at dynamic loop semantics.
    workflows = tx.execute(
        "SELECT * FROM studio_workflows WHERE is_official_preset=0 ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    for workflow in workflows:
        cid = _stable_id("canvas", workflow["user_id"], "legacy", workflow["id"])
        if tx.execute("SELECT 1 FROM studio_canvases WHERE id=?", (cid,)).fetchone():
            continue
        try:
            graph = json.loads(workflow["graph_json"])
            validate_canvas_document(graph)
        except (ValueError, TypeError, ServiceError):
            report["archivedWorkflows"] += 1
            continue
        if apply:
            with db.transaction() as write:
                write.execute(
                    "INSERT INTO studio_canvases(id,user_id,name,graph_json) VALUES(?,?,?,?::jsonb) ON CONFLICT(id) DO NOTHING",
                    (
                        cid,
                        workflow["user_id"],
                        workflow["title"],
                        json.dumps(graph, ensure_ascii=False),
                    ),
                )
        report["canvases"] += 1
    runs = tx.execute(
        """SELECT r.* FROM generation_runs r WHERE r.source='web'
           AND NOT EXISTS(SELECT 1 FROM studio_generations g WHERE g.run_id=r.id)
           AND EXISTS(SELECT 1 FROM studio_generations g WHERE g.user_id=r.user_id AND (g.id=r.external_run_id OR g.batch_id=r.external_run_id))
           ORDER BY r.id LIMIT ?""",
        (limit,),
    ).fetchall()
    for run in runs:
        executions = tx.execute(
            "SELECT * FROM studio_generations WHERE user_id=? AND (id=? OR batch_id=?) ORDER BY created_at,id",
            (run["user_id"], run["external_run_id"], run["external_run_id"]),
        ).fetchall()
        if any(g["status"] in ("queued", "running") for g in executions):
            report["issues"].append(
                {"runId": run["id"], "reason": "wait_for_inflight_generation"}
            )
            continue
        try:
            for generation in executions:
                ordinal = (
                    int(generation["batch_index"]) if generation["batch_id"] else 0
                )
                if not 0 <= ordinal < run["expected_count"]:
                    raise ValueError("invalid_legacy_plan_position")
                if generation["status"] == "success":
                    urls = _images(generation)
                    if not urls:
                        raise ValueError("missing_success_media")
                    for url in urls:
                        if not (
                            url.startswith(("/", "https://", "http://"))
                            and not url.startswith("//")
                            and ".." not in url.split("/")
                        ):
                            raise ValueError("invalid_legacy_media")
        except (ValueError, TypeError):
            report["issues"].append(
                {"runId": run["id"], "reason": "legacy_execution_requires_review"}
            )
            continue
        if apply:
            with db.transaction() as write:
                lock_generation_actor(write, run["user_id"])
                write.execute(
                    "SELECT id FROM generation_runs WHERE id=? FOR UPDATE", (run["id"],)
                ).fetchone()
                current = write.execute(
                    "SELECT * FROM studio_generations WHERE user_id=? AND (id=? OR batch_id=?) ORDER BY created_at,id FOR UPDATE",
                    (run["user_id"], run["external_run_id"], run["external_run_id"]),
                ).fetchall()
                if len(current) != len(executions) or any(
                    g["item_id"] or g["status"] in ("queued", "running")
                    for g in current
                ):
                    continue
                executions = current
                primary_ids = []
                created_ids = set()
                counts = {}
                for generation in executions:
                    ordinal = (
                        int(generation["batch_index"]) if generation["batch_id"] else 0
                    )
                    item = write.execute(
                        "SELECT id FROM generation_items WHERE run_id=? AND position=?",
                        (run["id"], ordinal * 1000),
                    ).fetchone()
                    if not item:
                        iid = _stable_id("item", run["id"], ordinal * 1000)
                        write.execute(
                            "INSERT INTO generation_items(id,run_id,position,status,created_at,updated_at) VALUES(?,?,?,'failed',?,?)",
                            (
                                iid,
                                run["id"],
                                ordinal * 1000,
                                utc_now_iso(),
                                utc_now_iso(),
                            ),
                        )
                        created_ids.add(iid)
                    else:
                        iid = item["id"]
                    primary_ids.append(iid)
                    counts[iid] = counts.get(iid, 0) + 1
                    write.execute(
                        "UPDATE generation_items SET ordinal=?,retired_at=NULL WHERE id=?",
                        (ordinal, iid),
                    )
                    write.execute(
                        "UPDATE studio_generations SET run_id=?,item_id=?,attempt_no=? WHERE id=?",
                        (run["id"], iid, counts[iid], generation["id"]),
                    )
                    if generation["status"] == "success":
                        for index, url in enumerate(_images(generation)):
                            media = _upsert_media(
                                write, owner_id=run["user_id"], url=url
                            )
                            if index == 0 and iid in created_ids:
                                write.execute(
                                    "UPDATE generation_items SET status='success',media_id=? WHERE id=?",
                                    (media, iid),
                                )
                            write.execute(
                                "INSERT INTO generation_attempt_media(attempt_id,media_id,ordinal) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                                (generation["id"], media, index),
                            )
                write.execute(
                    "UPDATE generation_items SET retired_at=now() WHERE run_id=? AND NOT(id=ANY(?))",
                    (run["id"], primary_ids),
                )
        report["runs"] += 1
        report["attempts"] += len(executions)
    report["ok"] = not report["issues"]
    return report
