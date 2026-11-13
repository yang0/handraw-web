"""Current article documents and independent illustration slots.

There is one document per ID. The save sequence is a concurrency token, never
a retained article revision. Illustration identity survives parameter edits.
"""

from __future__ import annotations

import hashlib
import json
import time

from .db import utc_now_iso
from .generation_v3 import _stable_id


_RUNTIME_CARD_FIELDS = {
    "imageUrl",
    "status",
    "errorText",
    "taskId",
    "requestId",
    "genId",
    "batchId",
    "batchIndex",
    "batchTotal",
    "generationMode",
    "demoMode",
    "variants",
    "_genCount",
    "selectedMediaId",
    "illustrationId",
    "activeAttemptId",
    "resultEpoch",
    "errorMsg",
    "engine",
    "updatedAt",
    "generatedAt",
}


def _error(message, *, status=400, code="invalid_article", extra=None):
    from .services import ServiceError

    return ServiceError(message, status=status, code=code, extra=extra)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def card_spec(card):
    return {
        k: v for k, v in card.items() if k not in _RUNTIME_CARD_FIELDS and k != "id"
    }


def spec_hash(spec):
    return hashlib.sha256(_json(spec).encode("utf-8")).hexdigest()


def execution_spec(card, article):
    """Resolve article defaults once; neither canvas nor form state is input."""
    settings = article.get("settings_json") or {}
    cover = card.get("role") == "cover"
    return {
        "prompt": str(card.get("prompt") or card.get("title") or "手绘文章配图"),
        "subject": str(
            card.get("subject") or card.get("theme") or card.get("title") or ""
        ).strip(),
        "ratio": card.get("ratio")
        or settings.get("coverRatio" if cover else "inlineRatio")
        or ("2.35:1" if cover else "4:3"),
        "style1": card.get("style1") or article["style1"] or "",
        "style2": card.get("style2", settings.get("style2", "")) or "",
        "layout": card.get("layoutId")
        or card.get("layout")
        or article["layout_code"]
        or "",
        "refImages": card.get("refImages") or [],
        "mode": card.get("mode") or settings.get("mode") or "graphic-text",
        "colors": card.get("colors", settings.get("colors", [])) or [],
        "tones": card.get("tones", settings.get("tones", [])) or [],
        "moods": card.get("moods", settings.get("moods", [])) or [],
        "whitespace": card.get("whitespace", settings.get("whitespace", "")) or "",
    }


def _owned_media(tx, uid, url):
    """Resolve a persisted user's file or an official static image to its ID."""
    if not url:
        return None
    url = str(url).split("?", 1)[0]
    found = tx.execute(
        "SELECT id FROM media_assets WHERE owner_user_id=? AND storage_key=?",
        (uid, url),
    ).fetchone()
    if found:
        return found["id"]
    if not (
        url.startswith("/images/") and ".." not in url.split("/") and "\\" not in url
    ):
        owned = tx.execute(
            "SELECT 1 FROM user_uploads WHERE user_id=? AND image_url=? AND deleted_at IS NULL "
            "UNION ALL SELECT 1 FROM studio_generation_media WHERE user_id=? AND media_url=? LIMIT 1",
            (uid, url, uid, url),
        ).fetchone()
        if not owned:
            raise _error(
                "配图不属于当前用户", status=403, code="article_media_forbidden"
            )
    mid = _stable_id("media", uid, url)
    tx.execute(
        "INSERT INTO media_assets(id,owner_user_id,storage_key,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT (id) DO NOTHING",
        (mid, uid, url, utc_now_iso()),
    )
    return mid


def sync_illustrations(tx, uid, article_id, cards):
    if not isinstance(cards, list) or len(cards) > 200:
        raise _error("文章配图必须为数组，最多 200 项", code="invalid_article_cards")
    existing = {
        r["local_id"]: r
        for r in tx.execute(
            "SELECT * FROM article_illustrations WHERE article_id=? FOR UPDATE",
            (article_id,),
        ).fetchall()
    }
    article = tx.execute(
        "SELECT style1,layout_code,settings_json FROM studio_articles WHERE id=?",
        (article_id,),
    ).fetchone()
    seen = set()
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise _error("文章配图项必须为对象", code="invalid_article_cards")
        local = str(card.get("id") or f"card_{index}")
        if local in seen or len(local) > 160:
            raise _error("文章配图编号重复或过长", code="invalid_article_cards")
        seen.add(local)
        spec = card_spec(card)
        digest = spec_hash(execution_spec(spec, article))
        anchor = {
            key: card[key]
            for key in ("afterBlockIdx", "anchorHeading", "anchorText", "placement")
            if key in card
        }
        old = existing.get(local)
        # An execution owns its result. A delayed browser workspace save cannot
        # replace a server-selected image or restore a superseded attempt.
        media = (
            old["selected_media_id"]
            if old
            else _owned_media(tx, uid, card.get("imageUrl"))
        )
        tx.execute(
            """INSERT INTO article_illustrations
              (id,article_id,local_id,role,sort_order,anchor_json,spec_json,spec_hash,selected_media_id)
              VALUES(?,?,?,?,?,?::jsonb,?::jsonb,?,?)
              ON CONFLICT(article_id,local_id) DO UPDATE SET
                role=excluded.role,sort_order=excluded.sort_order,anchor_json=excluded.anchor_json,
                spec_json=excluded.spec_json,spec_hash=excluded.spec_hash,deleted_at=NULL,updated_at=now(),
                active_attempt_id=CASE WHEN article_illustrations.spec_hash=excluded.spec_hash
                  AND article_illustrations.deleted_at IS NULL
                  THEN article_illustrations.active_attempt_id ELSE NULL END,
                result_epoch=article_illustrations.result_epoch + CASE
                  WHEN article_illustrations.spec_hash=excluded.spec_hash
                    AND article_illustrations.deleted_at IS NULL THEN 0 ELSE 1 END""",
            (
                _stable_id("ill", article_id, local),
                article_id,
                local,
                "cover" if card.get("role") == "cover" else "inline",
                index,
                _json(anchor),
                _json(spec),
                digest,
                media,
            ),
        )
    removed = [
        r["id"]
        for key, r in existing.items()
        if key not in seen and r["deleted_at"] is None
    ]
    if removed:
        tx.execute(
            "UPDATE article_illustrations SET deleted_at=now(),active_attempt_id=NULL,"
            "result_epoch=result_epoch+1 WHERE id=ANY(?)",
            (removed,),
        )


def hydrate_cards(tx, article_ids):
    """One query for every document's current illustration state."""
    grouped = {aid: [] for aid in article_ids}
    if not article_ids:
        return grouped
    rows = tx.execute(
        """SELECT i.*,m.storage_key,g.status AS attempt_status,g.id AS gen_id,
                  g.task_id,g.request_id,g.error_msg
           FROM article_illustrations i
           LEFT JOIN media_assets m ON m.id=i.selected_media_id
           LEFT JOIN studio_generations g ON g.id=i.active_attempt_id
           WHERE i.article_id=ANY(?) AND i.deleted_at IS NULL
           ORDER BY i.article_id,i.sort_order,i.id""",
        (list(article_ids),),
    ).fetchall()
    for row in rows:
        card = dict(row["spec_json"])
        card.update(
            id=row["local_id"],
            illustrationId=row["id"],
            selectedMediaId=row["selected_media_id"],
            resultEpoch=row["result_epoch"],
            imageUrl=row["storage_key"] or "",
        )
        state = row["attempt_status"]
        card["status"] = (
            "generating"
            if state in ("queued", "running")
            else "error"
            if state in ("refunded", "failed", "error", "cancelled")
            else "done"
            if card["imageUrl"]
            else "pending"
        )
        card.update(
            genId=row["gen_id"] or "",
            taskId=row["task_id"] or "",
            requestId=row["request_id"] or "",
        )
        grouped[row["article_id"]].append(card)
    return grouped


def save_articles(db, user, articles):
    uid = int(user["id"])
    if not isinstance(articles, list) or len(articles) > 50:
        raise _error("单次最多保存 50 篇文章")
    valid = [art for art in articles if isinstance(art, dict) and art.get("id")]
    ids = [str(art["id"]) for art in valid]
    if len(set(ids)) != len(ids):
        raise _error("保存请求中包含重复文章编号")
    versions, sequences = {}, {}
    with db.transaction() as tx:
        # Stable lock ordering covers both concurrent INSERT and UPDATE. This
        # does not retain versions: the article still has just its current row.
        for aid in sorted(ids):
            tx.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,208))", (aid,))
        for art in valid:
            aid = str(art["id"])
            row = tx.execute(
                "SELECT * FROM studio_articles WHERE id=? FOR UPDATE", (aid,)
            ).fetchone()
            if row and int(row["user_id"]) != uid:
                raise _error(
                    "无权修改其他用户的文章", status=403, code="article_forbidden"
                )
            if row and row["deleted_at"]:
                if "baseUpdatedAtMs" in art or "baseWriteSeq" in art:
                    raise _error(
                        "文章已经删除，请另存为新文章",
                        status=409,
                        code="article_deleted",
                        extra={"articleId": aid},
                    )
                continue
            title = str(art.get("articleTitle") or "未命名文章")[:140]
            markdown = str(art.get("markdown") or "")
            if row and row["illustrations_ready"]:
                stored_cards = [
                    {"id": slot["local_id"], **dict(slot["spec_json"])}
                    for slot in tx.execute(
                        "SELECT local_id,spec_json FROM article_illustrations WHERE article_id=? AND deleted_at IS NULL ORDER BY sort_order,id",
                        (aid,),
                    ).fetchall()
                ]
            else:
                stored_cards = json.loads(row["cards_json"] or "[]") if row else []
            cards = art.get("cards", stored_cards) or []
            if not isinstance(cards, list):
                raise _error("配图格式无效", code="invalid_article_cards")
            saved_cards = [
                {"id": str(card.get("id") or f"card_{index}"), **card_spec(card)}
                for index, card in enumerate(cards)
                if isinstance(card, dict)
            ]
            settings = art.get("settings") or {}
            if not isinstance(settings, dict):
                raise _error("文章设置格式无效")
            unchanged = row and all(
                (
                    row["article_title"] == title,
                    row["markdown"] == markdown,
                    [
                        {"id": str(c.get("id") or f"card_{index}"), **card_spec(c)}
                        for index, c in enumerate(stored_cards)
                    ]
                    == saved_cards,
                    row["style1"] == str(art.get("style1") or ""),
                    row["layout_code"] == str(art.get("layout") or ""),
                    row["status"] == str(art.get("status") or "ready"),
                    int(row["run_count"]) == int(art.get("runCount") or 0),
                    row["settings_json"] == settings,
                )
            )
            if not unchanged:
                for key, expected in (
                    ("baseWriteSeq", int(row["write_seq"]) if row else 0),
                    ("baseUpdatedAtMs", int(row["updated_at_ms"]) if row else 0),
                ):
                    if key not in art:
                        continue
                    try:
                        base = int(art[key])
                    except (ValueError, TypeError) as exc:
                        raise _error(
                            "文章保存序号无效", code="invalid_article_version"
                        ) from exc
                    if base != expected:
                        raise _error(
                            "文章在另一窗口已更新，本地稿未覆盖云端",
                            status=409,
                            code="article_version_conflict",
                            extra={"articleId": aid},
                        )
            stamp = (
                int(row["updated_at_ms"])
                if unchanged
                else max(
                    int(time.time() * 1000), int(row["updated_at_ms"]) + 1 if row else 1
                )
            )
            seq = (
                int(row["write_seq"])
                if unchanged
                else int(row["write_seq"]) + 1
                if row
                else 1
            )
            tx.execute(
                """INSERT INTO studio_articles
                   (id,user_id,article_title,markdown,cards_json,style1,layout_code,status,run_count,
                    created_at_ms,updated_at_ms,write_seq,settings_json,illustrations_ready)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?::jsonb,true)
                   ON CONFLICT(id) DO UPDATE SET article_title=excluded.article_title,markdown=excluded.markdown,
                    cards_json=excluded.cards_json,style1=excluded.style1,layout_code=excluded.layout_code,
                    status=excluded.status,run_count=excluded.run_count,updated_at_ms=excluded.updated_at_ms,
                    write_seq=excluded.write_seq,settings_json=excluded.settings_json,illustrations_ready=true""",
                (
                    aid,
                    uid,
                    title,
                    markdown,
                    "[]",
                    str(art.get("style1") or ""),
                    str(art.get("layout") or ""),
                    str(art.get("status") or "ready"),
                    int(art.get("runCount") or 0),
                    int(art.get("createdAtMs") or time.time() * 1000),
                    stamp,
                    seq,
                    _json(settings),
                ),
            )
            sync_illustrations(tx, uid, aid, cards)
            versions[aid], sequences[aid] = stamp, seq
    return {"ok": True, "versions": versions, "writeSequences": sequences}


def select_illustration_media(db, user, article_id, illustration_id, body):
    """Explicit selection is separate from autosaving document configuration."""
    with db.transaction() as tx:
        # Use the same document -> slot lock order as save and attempt creation.
        article = tx.execute(
            "SELECT id FROM studio_articles WHERE id=? AND user_id=? AND deleted_at='' FOR UPDATE",
            (article_id, user["id"]),
        ).fetchone()
        if not article:
            raise _error("文章不存在", status=404, code="article_not_found")
        slot = tx.execute(
            "SELECT * FROM article_illustrations WHERE article_id=? AND (id=? OR local_id=?) "
            "AND deleted_at IS NULL FOR UPDATE",
            (article_id, illustration_id, illustration_id),
        ).fetchone()
        if not slot:
            raise _error("文章配图不存在", status=404, code="illustration_not_found")
        base = body.get("baseResultEpoch")
        if type(base) is not int or base != slot["result_epoch"]:
            raise _error(
                "配图状态已变化，请刷新后重新选图",
                status=409,
                code="illustration_changed",
            )
        media_id = body.get("mediaId")
        if media_id:
            media = tx.execute(
                "SELECT id FROM media_assets WHERE id=? AND owner_user_id=?",
                (media_id, user["id"]),
            ).fetchone()
            if not media:
                raise _error(
                    "配图不属于当前用户", status=403, code="article_media_forbidden"
                )
        elif body.get("imageUrl"):
            media_id = _owned_media(tx, user["id"], body["imageUrl"])
        row = tx.execute(
            "UPDATE article_illustrations SET selected_media_id=?,active_attempt_id=NULL,"
            "result_epoch=result_epoch+1,updated_at=now() WHERE id=? RETURNING result_epoch",
            (media_id or None, slot["id"]),
        ).fetchone()
    return {
        "ok": True,
        "resultEpoch": row["result_epoch"],
        "selectedMediaId": media_id or None,
    }


def get_article(db, user, article_id):
    row = (
        db.get_conn()
        .execute(
            "SELECT * FROM studio_articles WHERE id=? AND user_id=? AND deleted_at=''",
            (article_id, user["id"]),
        )
        .fetchone()
    )
    if not row:
        raise _error("文章不存在", status=404, code="article_not_found")
    return {
        "ok": True,
        "article": {
            "id": row["id"],
            "articleTitle": row["article_title"],
            "markdown": row["markdown"],
            "style1": row["style1"],
            "layout": row["layout_code"],
            "status": row["status"],
            "cards": hydrate_cards(db.get_conn(), [article_id])[article_id]
            if row["illustrations_ready"]
            else json.loads(row["cards_json"] or "[]"),
            "runCount": row["run_count"],
            "writeSeq": row["write_seq"],
            "createdAtMs": row["created_at_ms"],
            "updatedAtMs": row["updated_at_ms"],
            "settings": row["settings_json"],
            "coverRatio": row["settings_json"].get("coverRatio", "2.35:1"),
            "inlineRatio": row["settings_json"].get("inlineRatio", "4:3"),
        },
    }
