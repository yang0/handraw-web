"""Owner-scoped canvas progress and explicit idempotent retries."""

from __future__ import annotations

import json
import re

from .studio_canvases import _error


def _owned_run(tx, user, rid, *, lock=False):
    row = tx.execute(
        "SELECT * FROM generation_runs WHERE id=? AND user_id=? AND creation_mode='canvas'"
        + (" FOR UPDATE" if lock else ""),
        (rid, user["id"]),
    ).fetchone()
    if not row:
        raise _error("批次不存在", status=404, code="run_not_found")
    return row


def _quote(tx,user,items):
    from .economy import pricing
    return pricing(tx,user["id"],items) if items else {"count":0,"totalCents":0,"freeCount":0,"items":[],"affordable":True}


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
            "SELECT COALESCE(SUM(amount_cents),0) FROM studio_generations WHERE run_id=? AND status='success'",
            (rid,),
        ).fetchone()[0]
    )
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
            "maxAmountCents": run["plan_json"].get("maxAmountCents", 0),
            "spentAmountCents": spent,
            "retryQuote": _quote(tx,user,[r["spec_json"] for r in rows if r["status"] in ("failed","cancelled")]),
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
            "quoteId": body.get("quoteId"),
            "maxAmountCents": body.get("maxAmountCents"),
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
            "SELECT id,spec_json FROM generation_items WHERE run_id=? AND status IN ('failed','cancelled') ORDER BY ordinal FOR UPDATE",
            (rid,),
        ).fetchall()
        if not rows:
            return {"ok": True, "runId": rid, "idempotent": True}
        from .economy import reserve_quote
        lines=reserve_quote(tx,user["id"],str(body.get("quoteId") or ""),key)
        if len(lines)!=len(rows) or type(body.get("maxAmountCents")) is not int or sum(x["amountCents"] for x in lines)>body["maxAmountCents"]:
            raise _error("重试费用需要重新确认",status=409,code="canvas_budget_required")
        for index,(row,line) in enumerate(zip(rows,lines)):
            if line["spec"]["id"]!=row["spec_json"].get("specId","standard-1k") or line["spec"]["ratio"]!=row["spec_json"].get("ratio","3:4"):
                raise _error("重试规格与报价不符",status=409,code="quote_spec_mismatch")
            tx.execute("UPDATE generation_charges SET item_id=? WHERE quote_id=? AND position=?",(row["id"],body["quoteId"],index))
        plan=dict(run["plan_json"])
        plan["maxAmountCents"]=plan.get("maxAmountCents",0)+body["maxAmountCents"]
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
