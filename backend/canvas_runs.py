"""Owner-scoped canvas progress and explicit idempotent retries."""

from __future__ import annotations

import json
import re

from .studio_canvases import _error, quote_count


def _owned_run(tx, user, rid, *, lock=False):
    row = tx.execute(
        "SELECT * FROM generation_runs WHERE id=? AND user_id=? AND creation_mode='canvas'"
        + (" FOR UPDATE" if lock else ""),
        (rid, user["id"]),
    ).fetchone()
    if not row:
        raise _error("批次不存在", status=404, code="run_not_found")
    return row


def _quote(tx, user, count):
    from .services import get_site_settings, get_wallet_quota_state

    settings = get_site_settings(tx)
    wallet = get_wallet_quota_state(tx, user["id"], settings)
    return quote_count(
        {
            "unitPrice": max(
                0, int(settings.get("economy", {}).get("studio_credit_per_image", 2))
            ),
            "freeRemaining": wallet["freeQuotaRemaining"],
            "balance": wallet["balance"],
        },
        count,
    )


def list_canvas_runs(db, user, cid, *, cursor="", limit=20):
    from .studio_paging import read_cursor, next_cursor

    kind = "canvas-runs:" + cid
    after = read_cursor(cursor, kind, limit)
    boundary = " AND (created_at,id)<(?,?)" if after else ""
    rows = (
        db.get_conn()
        .execute(
            "SELECT id,status,expected_count,created_at FROM generation_runs WHERE user_id=? AND canvas_id=? "
            "AND creation_mode='canvas'"
            + boundary
            + " ORDER BY created_at DESC,id DESC LIMIT ?",
            (user["id"], cid, *(after or ()), limit + 1),
        )
        .fetchall()
    )
    return {
        "ok": True,
        "items": [
            {
                "id": r["id"],
                "status": r["status"],
                "count": r["expected_count"],
                "createdAt": r["created_at"],
            }
            for r in rows[:limit]
        ],
        "nextCursor": next_cursor(kind, rows, limit, "created_at"),
    }


def get_canvas_run(db, user, rid):
    tx = db.get_conn()
    run = _owned_run(tx, user, rid)
    rows = tx.execute(
        "SELECT id,ordinal,status,error_code,spec_json FROM generation_items WHERE run_id=? ORDER BY ordinal,id",
        (rid,),
    ).fetchall()
    media = tx.execute(
        """WITH latest AS (
             SELECT DISTINCT ON(item_id) id,item_id FROM studio_generations
             WHERE run_id=? AND status='success' AND item_id IS NOT NULL ORDER BY item_id,attempt_no DESC,id DESC
           ) SELECT l.item_id,array_agg(m.storage_key ORDER BY am.ordinal) AS images FROM latest l
           JOIN generation_attempt_media am ON am.attempt_id=l.id JOIN media_assets m ON m.id=am.media_id GROUP BY l.item_id""",
        (rid,),
    ).fetchall()
    by_item = {r["item_id"]: r["images"] for r in media}
    spent = int(
        tx.execute(
            "SELECT COALESCE(SUM(credits_spent),0) FROM studio_generations WHERE run_id=? AND status<>'refunded'",
            (rid,),
        ).fetchone()[0]
    )
    failed = sum(r["status"] in ("failed", "cancelled") for r in rows)
    # Task ordinals are compacted after selecting combinations. The frozen
    # items keep that order and retain the original output node IDs.
    plan_items = run["plan_json"].get("items", [])
    output_nodes = {
        index: item.get("outputNodeId")
        for index, item in enumerate(plan_items)
        if isinstance(item, dict)
    }
    return {
        "ok": True,
        "run": {
            "id": rid,
            "canvasId": run["canvas_id"],
            "createdAt": run["created_at"],
            "batchId": run["external_run_id"],
            "status": run["status"],
            "count": run["expected_count"],
            "maxCredits": run["plan_json"].get("maxCredits", 0),
            "spentCredits": spent,
            "retryQuote": _quote(tx, user, failed),
            "items": [
                {
                    "id": r["id"],
                    "ordinal": r["ordinal"],
                    "status": r["status"],
                    "errorCode": r["error_code"],
                    "outputNodeId": output_nodes.get(r["ordinal"]),
                    "spec": r["spec_json"],
                    "images": by_item.get(r["id"], []),
                }
                for r in rows
            ],
        },
    }


def retry_canvas_run(db, user, rid, body):
    key = str(body.get("requestId") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", key):
        raise _error("重试需要稳定的请求编号")
    from .studio_execution import lock_generation_actor

    with db.transaction() as tx:
        lock_generation_actor(tx, user["id"])
        run = _owned_run(tx, user, rid, lock=True)
        previous = tx.execute(
            "SELECT payload_json FROM canvas_run_requests WHERE run_id=? AND request_id=?",
            (rid, key),
        ).fetchone()
        payload = {
            "maxCredits": body.get("maxCredits"),
            "unitPrice": body.get("unitPrice"),
        }
        if previous:
            if previous["payload_json"] != payload:
                raise _error(
                    "重试请求编号已用于不同操作",
                    status=409,
                    code="canvas_request_conflict",
                )
            return {"ok": True, "runId": rid, "idempotent": True}
        rows = tx.execute(
            "SELECT id FROM generation_items WHERE run_id=? AND status IN ('failed','cancelled') FOR UPDATE",
            (rid,),
        ).fetchall()
        if not rows:
            return {"ok": True, "runId": rid, "idempotent": True}
        quote = _quote(tx, user, len(rows))
        spent = int(
            tx.execute(
                "SELECT COALESCE(SUM(credits_spent),0) FROM studio_generations WHERE run_id=? AND status<>'refunded'",
                (rid,),
            ).fetchone()[0]
        )
        limit = body.get("maxCredits")
        if (
            type(limit) is not int
            or limit < spent + quote["total"]
            or not quote["affordable"]
            or body.get("unitPrice") != quote["unitPrice"]
        ):
            raise _error(
                "重试费用已变化，请重新确认", status=409, code="canvas_budget_required"
            )
        plan = dict(run["plan_json"])
        plan.update(maxCredits=limit, unitPrice=quote["unitPrice"])
        tx.execute(
            "INSERT INTO canvas_run_requests(run_id,request_id,payload_json) VALUES(?,?,?::jsonb)",
            (rid, key, json.dumps(payload)),
        )
        tx.execute(
            "UPDATE generation_runs SET plan_json=?::jsonb,status='running' WHERE id=?",
            (json.dumps(plan, ensure_ascii=False), rid),
        )
        tx.execute(
            "UPDATE generation_items SET status='pending',error_code='',dispatch_request_id='',dispatch_token=NULL,"
            "dispatch_until=NULL,dispatch_after=now() WHERE id=ANY(?)",
            ([r["id"] for r in rows],),
        )
    return {"ok": True, "runId": rid, "retryCount": len(rows)}
