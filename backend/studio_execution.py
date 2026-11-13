"""Direct authoring-source, plan-item and execution-attempt relationships."""

from __future__ import annotations

import json

from .db import utc_now_iso
from .generation_v3 import _stable_id, _upsert_media


def _error(message, *, status=409, code="generation_source_conflict"):
    from .services import ServiceError

    return ServiceError(message, status=status, code=code)


def lock_generation_actor(tx, uid):
    tx.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,210))", (str(uid),))


def task_position(tx, run_id, ordinal):
    existing = tx.execute(
        "SELECT position FROM generation_items WHERE run_id=? AND ordinal=?",
        (run_id, ordinal),
    ).fetchone()
    if existing:
        return int(existing["position"])
    legacy = tx.execute(
        "SELECT 1 FROM generation_items WHERE run_id=? AND ordinal IS NULL LIMIT 1",
        (run_id,),
    ).fetchone()
    # Only pre-cutover snapshots retain their encoded keys. New tasks use one
    # ordinary sequence number; attempt-media ordinal is an independent field.
    return ordinal * 1000 if legacy else ordinal


def lock_attempt(tx, attempt_id, *, poll_claim_token=None):
    """Serialize a run before locking its attempt and illustration rows."""
    row = tx.execute(
        "SELECT run_id,user_id FROM studio_generations WHERE id=?", (attempt_id,)
    ).fetchone()
    if row and row["user_id"] is not None:
        lock_generation_actor(tx, row["user_id"])
    if row and row["run_id"]:
        tx.execute(
            "SELECT id FROM generation_runs WHERE id=? FOR UPDATE", (row["run_id"],)
        ).fetchone()
    generation = tx.execute(
        "SELECT * FROM studio_generations WHERE id=? FOR UPDATE", (attempt_id,)
    ).fetchone()
    if (
        poll_claim_token is not None
        and not tx.execute(
            "SELECT 1 FROM studio_generations WHERE id=? AND poll_claim_token=? AND poll_claim_until>now()",
            (attempt_id, poll_claim_token),
        ).fetchone()
    ):
        return None
    return generation


def apply_source_input(db, user, body):
    """Resolve saved authoring input before reserving any quota or credits."""
    if body.get("creationSource") == "article" and not body.get("articleId"):
        raise _error(
            "文章配图必须指定已保存的文章与配图位", status=400, code="article_required"
        )
    if body.get("creationSource") == "canvas" and not body.get("canvasId"):
        raise _error(
            "参数画布必须先提交组合批次", status=400, code="canvas_plan_required"
        )
    if not body.get("canvasId"):
        for key in ("_canvasResourceInputs", "_canvasRunId", "_canvasDispatchToken", "_canvasItemId"):
            body.pop(key, None)
    if body.get("canvasId"):
        if (
            body.get("articleId")
            or body.get("recipeId")
            or body.get("creationSource") != "canvas"
        ):
            raise _error("画布任务不能关联其他表单")
        run = (
            db.get_conn()
            .execute(
                "SELECT * FROM generation_runs WHERE user_id=? AND source='web' AND external_run_id=? AND canvas_id=?",
                (user["id"], body.get("batchId"), body["canvasId"]),
            )
            .fetchone()
        )
        if not run or not run["plan_json"]:
            raise _error("请先预览并提交画布组合清单", code="canvas_plan_required")
        try:
            index = int(body.get("batchIndex", 0))
            item = run["plan_json"]["items"][index]
            if index < 0:
                raise IndexError
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise _error("组合项不存在") from exc
        spec = item["spec"]
        claim = (
            db.get_conn()
            .execute(
                "SELECT id FROM generation_items WHERE run_id=? AND ordinal=? AND dispatch_token=? AND dispatch_until>now()",
                (run["id"], index, body.get("_canvasDispatchToken")),
            )
            .fetchone()
        )
        if not claim:
            raise _error(
                "画布批次由后台执行，请在批次中查看或重试",
                code="canvas_dispatch_required",
            )
        for key in (
            "prompt",
            "style1",
            "style2",
            "layout",
            "ratio",
            "refImages",
            "colors",
            "tones",
            "moods",
            "whitespace",
            "mode",
            "specId",
        ):
            if key in body and body[key] != spec.get(
                key, "3:4" if key == "ratio" else [] if key == "refImages" else ""
            ):
                raise _error(
                    "已提交组合参数不能修改，请创建新批次", code="canvas_plan_changed"
                )
        body.update(spec)
        body.update(
            batchTotal=run["expected_count"], batchIndex=index, creationSource="canvas"
        )
        body["_canvasRunId"] = run["id"]
        body["_canvasItemId"] = claim["id"]
        body["_canvasResourceInputs"] = run["plan_json"].get("resourceInputs", {})
        body["promptFromSkill"] = False
        body.pop("historyId", None)
        body.pop("generationId", None)
        body.pop("useCh001", None)
        body.pop("customRefImg", None)
    if body.get("articleId"):
        if body.get("creationSource") != "article" or body.get("canvasId"):
            raise _error("文章配图来源无效")
        row = (
            db.get_conn()
            .execute(
                "SELECT i.*,a.style1,a.layout_code,a.settings_json FROM article_illustrations i JOIN studio_articles a ON a.id=i.article_id "
                "WHERE a.id=? AND a.user_id=? AND a.deleted_at='' AND i.deleted_at IS NULL "
                "AND (i.local_id=? OR i.id=?)",
                (
                    body["articleId"],
                    user["id"],
                    str(body.get("cardId") or body.get("illustrationId") or ""),
                    str(body.get("cardId") or body.get("illustrationId") or ""),
                ),
            )
            .fetchone()
        )
        if not row:
            raise _error("文章配图不存在", status=404, code="illustration_not_found")
        from .studio_articles import execution_spec

        effective = execution_spec(row["spec_json"], row)
        if body.get("recipeId"):
            raise _error("文章配图不能读取其他表单")
        for key, value in effective.items():
            if key in body and body[key] != value:
                raise _error(
                    "配图要求已修改，请先保存后生成", code="illustration_changed"
                )
        body.update(effective)
        for key in (
            "historyId",
            "generationId",
            "useCh001",
            "customRefImg",
            "topic",
            "theme",
        ):
            body.pop(key, None)
        saved_card = row["spec_json"]
        body["promptFromSkill"] = bool(str(saved_card.get("prompt") or "").strip())
        body["recipeSnapshot"] = {
            key: effective[key] for key in ("style1", "style2", "layout")
        }
        body["recipeSnapshot"]["subject"] = body["subject"]
        body["illustrationSpecHash"] = row["spec_hash"]
        body["illustrationEpoch"] = row["result_epoch"]


def attach_attempt(tx, uid, run_id, attempt_id, body):
    run = tx.execute(
        "SELECT * FROM generation_runs WHERE id=? FOR UPDATE", (run_id,)
    ).fetchone()
    mode = str(body.get("creationSource") or "other")
    if mode not in ("quick", "batch", "article", "canvas"):
        mode = "other"
    article_id, canvas_id = body.get("articleId"), body.get("canvasId")
    if article_id and (mode != "article" or canvas_id):
        raise _error("文章配图不能关联画布或其他表单")
    if canvas_id and mode != "canvas":
        raise _error("画布任务来源无效")
    if article_id:
        article = tx.execute(
            "SELECT id FROM studio_articles WHERE id=? AND user_id=? AND deleted_at='' FOR UPDATE",
            (article_id, uid),
        ).fetchone()
        if not article:
            raise _error("文章不存在", status=404, code="article_not_found")
    if (
        canvas_id
        and not tx.execute(
            "SELECT 1 FROM studio_canvases WHERE id=? AND user_id=?",
            (canvas_id, uid),
        ).fetchone()
    ):
        raise _error("画布不存在", status=404, code="canvas_not_found")
    if run["creation_mode"] != "other" and (
        run["creation_mode"] != mode
        or run["article_id"] != article_id
        or run["canvas_id"] != canvas_id
    ):
        raise _error("不能改变批次所属的创作入口")
    tx.execute(
        "UPDATE generation_runs SET creation_mode=?,article_id=COALESCE(article_id,?),canvas_id=COALESCE(canvas_id,?) WHERE id=?",
        (mode, article_id, canvas_id, run_id),
    )
    ordinal = int(body.get("batchIndex") or 0)
    if (
        canvas_id
        and not tx.execute(
            "SELECT id FROM generation_items WHERE run_id=? AND ordinal=? AND dispatch_token=? AND dispatch_until>now() FOR UPDATE",
            (run_id, ordinal, body.get("_canvasDispatchToken")),
        ).fetchone()
    ):
        raise _error("画布任务已由其他工作进程接管", code="canvas_dispatch_expired")
    position = task_position(tx, run_id, ordinal)
    item_id = _stable_id("item", run_id, position)
    illustration = None
    if article_id:
        card_id = str(body.get("cardId") or body.get("illustrationId") or "")
        illustration = tx.execute(
            "SELECT * FROM article_illustrations WHERE article_id=? AND (local_id=? OR id=?) "
            "AND deleted_at IS NULL FOR UPDATE",
            (article_id, card_id, card_id),
        ).fetchone()
        if not illustration:
            raise _error("配图位置不存在", status=404, code="illustration_not_found")
        if (
            body.get("illustrationSpecHash")
            and body["illustrationSpecHash"] != illustration["spec_hash"]
        ):
            raise _error("配图要求已修改，请重新提交", code="illustration_changed")
        if (
            "illustrationEpoch" in body
            and body["illustrationEpoch"] != illustration["result_epoch"]
        ):
            raise _error("配图状态已变化，请重新提交", code="illustration_changed")
    plan = {
        key: body[key]
        for key in (
            "prompt",
            "ratio",
            "style1",
            "style2",
            "layout",
            "refImages",
            "recipeSnapshot",
            "colors",
            "tones",
            "moods",
            "whitespace",
            "mode",
        )
        if key in body
    }
    tx.execute(
        """INSERT INTO generation_items(id,run_id,position,ordinal,status,spec_json,illustration_id,created_at,updated_at)
           VALUES(?,?,?,?,'generating',?::jsonb,?,?,?)
           ON CONFLICT(run_id,position) DO UPDATE SET ordinal=excluded.ordinal,status='generating',
             spec_json=excluded.spec_json,illustration_id=COALESCE(generation_items.illustration_id,excluded.illustration_id),
             error_code='',updated_at=excluded.updated_at""",
        (
            item_id,
            run_id,
            position,
            ordinal,
            json.dumps(plan, ensure_ascii=False),
            illustration["id"] if illustration else None,
            utc_now_iso(),
            utc_now_iso(),
        ),
    )
    attempt_no = (
        int(
            tx.execute(
                "SELECT COUNT(*) FROM studio_generations WHERE item_id=?", (item_id,)
            ).fetchone()[0]
        )
        + 1
    )
    tx.execute(
        "UPDATE studio_generations SET run_id=?,item_id=?,attempt_no=?,input_json=?::jsonb,illustration_spec_hash=? WHERE id=?",
        (
            run_id,
            item_id,
            attempt_no,
            json.dumps(plan, ensure_ascii=False),
            illustration["spec_hash"] if illustration else "",
            attempt_id,
        ),
    )
    if illustration:
        epoch = tx.execute(
            "UPDATE article_illustrations SET active_attempt_id=?,result_epoch=result_epoch+1,updated_at=now() "
            "WHERE id=? RETURNING result_epoch",
            (attempt_id, illustration["id"]),
        ).fetchone()["result_epoch"]
        tx.execute(
            "UPDATE studio_generations SET illustration_epoch=? WHERE id=?",
            (epoch, attempt_id),
        )
    return item_id


def record_attempt_media(tx, generation, urls):
    """Retain each attempt's results even when a later attempt supersedes it."""
    if not generation:
        return
    uid = int(generation["user_id"])
    for index, url in enumerate(urls):
        mid = _upsert_media(tx, owner_id=uid, url=str(url))
        tx.execute(
            "INSERT INTO generation_attempt_media(attempt_id,media_id,ordinal) VALUES(?,?,?) "
            "ON CONFLICT(attempt_id,ordinal) DO NOTHING",
            (generation["id"], mid, index),
        )
        if index == 0:
            if generation.get("item_id") and is_current_attempt(tx, generation):
                tx.execute(
                    "UPDATE generation_items SET status='success',media_id=?,error_code='',updated_at=? WHERE id=?",
                    (mid, utc_now_iso(), generation["item_id"]),
                )
            tx.execute(
                """UPDATE article_illustrations i SET selected_media_id=?,updated_at=now()
                   WHERE active_attempt_id=? AND deleted_at IS NULL AND spec_hash=? AND result_epoch=?
                     AND EXISTS(SELECT 1 FROM studio_articles a WHERE a.id=i.article_id AND a.deleted_at='')""",
                (
                    mid,
                    generation["id"],
                    generation.get("illustration_spec_hash") or "",
                    generation.get("illustration_epoch"),
                ),
            )


def is_current_attempt(tx, generation):
    if not generation or not generation.get("item_id"):
        return True
    current = tx.execute(
        "SELECT id FROM studio_generations WHERE item_id=? ORDER BY attempt_no DESC,id DESC LIMIT 1",
        (generation["item_id"],),
    ).fetchone()
    return bool(current and current["id"] == generation["id"])
