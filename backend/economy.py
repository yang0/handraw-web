"""Cash and resolution-scoped benefits. All mutations require a caller transaction."""

from __future__ import annotations

import hashlib
import json
import uuid


def error(message, code="billing_invalid", status=400):
    from .services import ServiceError

    return ServiceError(message, code=code, status=status)


def integer(value, minimum=0, maximum=100000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise error("请输入有效的整数金额或数量")
    return value


def lock_user(tx, uid):
    from .studio_execution import lock_generation_actor

    lock_generation_actor(tx, int(uid))


def cash(tx, uid):
    row = tx.execute("SELECT * FROM cash_accounts WHERE user_id=?", (uid,)).fetchone()
    return {
        "balanceCents": int(row["balance_cents"]) if row else 0,
        "heldCents": int(row["held_cents"]) if row else 0,
    }


def cash_delta(
    tx, uid, delta, held, kind, key, *, ref="", reason="", actor=None, debt=False
):
    lock_user(tx, uid)
    tx.execute(
        "INSERT INTO cash_accounts(user_id) VALUES(?) ON CONFLICT DO NOTHING", (uid,)
    )
    account = tx.execute(
        "SELECT * FROM cash_accounts WHERE user_id=? FOR UPDATE", (uid,)
    ).fetchone()
    if tx.execute("SELECT 1 FROM cash_entries WHERE event_key=?", (key,)).fetchone():
        return cash(tx, uid), False
    balance = account["balance_cents"] + delta
    frozen = account["held_cents"] + held
    if frozen < 0 or balance < 0 and not debt:
        raise error("生图余额不足，请先充值", "insufficient_cash")
    tx.execute(
        "UPDATE cash_accounts SET balance_cents=?,held_cents=?,updated_at=now() WHERE user_id=?",
        (balance, frozen, uid),
    )
    tx.execute(
        "INSERT INTO cash_entries(user_id,event_key,kind,delta_cents,held_delta_cents,balance_after_cents,ref_id,reason,actor_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (uid, key, kind, delta, held, balance, ref, reason, actor),
    )
    return cash(tx, uid), True


def quota(tx, uid, resolution="1k"):
    policy = tx.execute(
        "SELECT base_units FROM generation_quota_policy WHERE resolution=?",
        (resolution,),
    ).fetchone()
    base = int(policy[0]) if policy else 0
    counts = {
        r["quota_source"]: (int(r["used"]), int(r["held"]))
        for r in tx.execute(
            "SELECT quota_source,count(*) FILTER(WHERE status='settled') used,count(*) FILTER(WHERE status='reserved') held FROM generation_charges WHERE user_id=? AND resolution=? AND quota_source IS NOT NULL AND status IN ('reserved','settled') GROUP BY quota_source",
            (uid, resolution),
        ).fetchall()
    }
    used, held = counts.get("base", (0, 0))
    sources = [
        {
            "id": "base",
            "total": base,
            "used": used,
            "held": held,
            "remaining": max(0, base - used - held),
        }
    ]
    # Expiring gifts are spent first, then the perpetual basic allowance.
    gifts = []
    for row in tx.execute(
        "SELECT id,units FROM generation_quota_grants WHERE user_id=? AND resolution=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>now()) ORDER BY expires_at NULLS LAST,created_at,id",
        (uid, resolution),
    ).fetchall():
        used, held = counts.get(row["id"], (0, 0))
        gifts.append(
            {
                "id": row["id"],
                "total": row["units"],
                "used": used,
                "held": held,
                "remaining": max(0, row["units"] - used - held),
            }
        )
    sources = gifts + sources
    return {
        "resolution": resolution,
        "baseUnits": base,
        "total": sum(x["total"] for x in sources),
        "used": sum(x[0] for x in counts.values()),
        "held": sum(x[1] for x in counts.values()),
        "remaining": sum(x["remaining"] for x in sources),
        "sources": sources,
    }


def public_spec(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "model": row["model"],
        "resolution": row["resolution"],
        "quality": row["quality"],
        "sizes": row["sizes_json"],
        "priceCents": row["price_cents"],
        "version": row["version"],
        "verified": row["verified"],
        "enabled": row["enabled"],
    }


def specs(tx):
    return [
        public_spec(r)
        for r in tx.execute(
            "SELECT * FROM generation_specs WHERE enabled=true ORDER BY resolution,id"
        ).fetchall()
    ]


def resolve_spec(tx, body, *, lock=False):
    sid = str(body.get("specId") or "standard-1k")
    row = tx.execute(
        "SELECT * FROM generation_specs WHERE id=? AND enabled=true"
        + (" FOR SHARE" if lock else ""),
        (sid,),
    ).fetchone()
    if not row or not row["verified"]:
        raise error("此生图规格尚未验证开放，请联系管理员配置", "spec_unavailable", 409)
    ratio = str(body.get("ratio") or "3:4")
    size = row["sizes_json"].get(ratio)
    if not size:
        raise error("当前规格不支持此比例", "spec_ratio_unsupported")
    return {**public_spec(row), "size": size, "ratio": ratio}


def pricing(tx, uid, bodies):
    remaining = {}
    lines = []
    for body in bodies:
        if body.get("slotPosition") is not None:
            integer(body["slotPosition"], maximum=199)
        spec = resolve_spec(tx, body)
        resolution = spec["resolution"]
        if resolution not in remaining:
            remaining[resolution] = quota(tx, uid, resolution)["remaining"]
        free = remaining[resolution] > 0
        if free:
            remaining[resolution] -= 1
        if not free and spec["priceCents"] is None:
            raise error("当前规格尚未配置收费价格", "price_not_configured", 409)
        lines.append(
            {
                "spec": spec,
                "free": free,
                "amountCents": 0 if free else spec["priceCents"],
                "slotPosition": body.get("slotPosition"),
            }
        )
    total = sum(x["amountCents"] for x in lines)
    return {
        "items": lines,
        "count": len(lines),
        "freeCount": sum(x["free"] for x in lines),
        "totalCents": total,
        "balanceCents": cash(tx, uid)["balanceCents"],
        "affordable": cash(tx, uid)["balanceCents"] >= total,
        "currency": "CNY",
    }


def create_quote(db, user, bodies):
    if (
        not isinstance(bodies, list)
        or not 1 <= len(bodies) <= 200
        or any(not isinstance(x, dict) for x in bodies)
    ):
        raise error("报价需要1至200张图片的规格")
    release_abandoned_quotes(db, user["id"])
    with db.transaction() as tx:
        normalized = []
        for body in bodies:
            body = dict(body)
            if body.get("recipeId"):
                recipe = tx.execute(
                    "SELECT ratio FROM studio_recipes WHERE id=? AND user_id=?",
                    (body["recipeId"], user["id"]),
                ).fetchone()
                if not recipe:
                    raise error("配方不存在或无权访问", "recipe_not_found", 404)
                body["ratio"] = recipe["ratio"] or "3:4"
            normalized.append(body)
        quote = pricing(tx, user["id"], normalized)
        qid = "quote_" + uuid.uuid4().hex
        expiry = tx.execute(
            "INSERT INTO generation_quotes(id,user_id,items_json,total_cents,expires_at) VALUES(?,?,?::jsonb,?,now()+interval '10 minutes') RETURNING expires_at",
            (qid, user["id"], json.dumps(quote["items"]), quote["totalCents"]),
        ).fetchone()[0]
    return {"ok": True, **quote, "quoteId": qid, "expiresAt": expiry.isoformat()}


def reserve_quote(tx, uid, qid, request_key):
    lock_user(tx, uid)
    row = tx.execute(
        "SELECT *,expires_at>now() valid FROM generation_quotes WHERE id=? AND user_id=? FOR UPDATE",
        (qid, uid),
    ).fetchone()
    if not row:
        raise error("请先预览并确认本次生图费用", "quote_required", 409)
    if row["reserved_at"]:
        if row["request_key"] != request_key:
            raise error("报价已用于其他任务", "quote_conflict", 409)
        return row["items_json"]
    if not row["valid"]:
        raise error("报价已过期，请重新确认", "quote_expired", 409)
    lines = row["items_json"]
    availability = {}
    for index, line in enumerate(lines):
        spec = line["spec"]
        current = resolve_spec(
            tx, {"specId": spec["id"], "ratio": spec["ratio"]}, lock=True
        )
        if current != spec:
            raise error("生图规格或价格已更新，请重新确认", "price_changed", 409)
        source = None
        if line["free"]:
            resolution = spec["resolution"]
            if resolution not in availability:
                availability[resolution] = quota(tx, uid, resolution)["sources"]
            source_row = next(
                (s for s in availability[resolution] if s["remaining"] > 0), None
            )
            if source_row is None:
                raise error(
                    "免费额度已被其他任务使用，请重新确认费用", "quota_changed", 409
                )
            source_row["remaining"] -= 1
            source = source_row["id"]
        tx.execute(
            "INSERT INTO generation_charges(id,quote_id,position,user_id,spec_json,resolution,quota_source,amount_cents,slot_position) VALUES(?,?,?,?,?::jsonb,?,?,?,?)",
            (
                f"{qid}:{index}",
                qid,
                index,
                uid,
                json.dumps(spec),
                spec["resolution"],
                source,
                line["amountCents"],
                line.get("slotPosition"),
            ),
        )
    if row["total_cents"]:
        cash_delta(
            tx,
            uid,
            -row["total_cents"],
            row["total_cents"],
            "generation_hold",
            "hold:" + qid,
            ref=qid,
        )
        for index, line in enumerate(lines):
            needed = line["amountCents"]
            for lot in tx.execute(
                "SELECT * FROM cash_lots WHERE user_id=? AND remaining_cents>0 ORDER BY created_at,order_id FOR UPDATE",
                (uid,),
            ).fetchall():
                amount = min(needed, lot["remaining_cents"])
                if not amount:
                    break
                tx.execute(
                    "UPDATE cash_lots SET remaining_cents=remaining_cents-? WHERE order_id=?",
                    (amount, lot["order_id"]),
                )
                tx.execute(
                    "INSERT INTO cash_allocations(charge_id,order_id,amount_cents) VALUES(?,?,?)",
                    (f"{qid}:{index}", lot["order_id"], amount),
                )
                needed -= amount
    tx.execute(
        "UPDATE generation_quotes SET reserved_at=now(),request_key=? WHERE id=?",
        (request_key, qid),
    )
    return lines


def attach_charge(tx, uid, generation_id, body):
    lock_user(tx, uid)
    item_id = body.get("_canvasItemId")
    if item_id:
        charge = tx.execute(
            "SELECT * FROM generation_charges WHERE item_id=? AND status='reserved' FOR UPDATE",
            (item_id,),
        ).fetchone()
    else:
        qid = str(body.get("quoteId") or "")
        position = integer(body.get("quoteIndex", 0), maximum=199)
        key = "generation:" + qid
        reserve_quote(tx, uid, qid, key)
        batch = str(body.get("batchId") or "")
        bound = tx.execute(
            "SELECT batch_key FROM generation_quotes WHERE id=? FOR UPDATE", (qid,)
        ).fetchone()[0]
        if bound is not None and bound != batch:
            raise error("报价已绑定其他批次", "quote_conflict", 409)
        tx.execute("UPDATE generation_quotes SET batch_key=? WHERE id=?", (batch, qid))
        charge = tx.execute(
            "SELECT * FROM generation_charges WHERE quote_id=? AND position=? AND user_id=? FOR UPDATE",
            (qid, position, uid),
        ).fetchone()
    if (
        not charge
        or charge["user_id"] != uid
        or charge["status"] != "reserved"
        or charge["generation_id"]
        and charge["generation_id"] != generation_id
    ):
        raise error("生图费用预占不存在或已使用", "charge_conflict", 409)
    requested = {
        "specId": body.get("specId") or charge["spec_json"]["id"],
        "ratio": body.get("ratio") or "3:4",
    }
    if (
        requested["specId"] != charge["spec_json"]["id"]
        or requested["ratio"] != charge["spec_json"]["ratio"]
    ):
        raise error("任务规格与已确认报价不符", "quote_spec_mismatch", 409)
    tx.execute(
        "UPDATE generation_charges SET generation_id=?,updated_at=now() WHERE id=?",
        (generation_id, charge["id"]),
    )
    spec = charge["spec_json"]
    tx.execute(
        "UPDATE studio_generations SET spec_id=?,amount_cents=?,billing_snapshot=?::jsonb,cost_type=? WHERE id=?",
        (
            spec["id"],
            charge["amount_cents"],
            json.dumps(spec),
            "free_entitlement" if charge["quota_source"] else "cash",
            generation_id,
        ),
    )
    return charge


def finish_charge(tx, generation_id, *, success):
    row = tx.execute(
        "SELECT * FROM generation_charges WHERE generation_id=? FOR UPDATE",
        (generation_id,),
    ).fetchone()
    if row:
        finish_reservation(tx, row, success=success)


def finish_reservation(tx, row, *, success=False):
    if row["status"] != "reserved":
        return
    lock_user(tx, row["user_id"])
    status = "settled" if success else "released"
    changed = tx.execute(
        "UPDATE generation_charges SET status=?,updated_at=now() WHERE id=? AND status='reserved' RETURNING id",
        (status, row["id"]),
    ).fetchone()
    if changed and row["amount_cents"]:
        amount = row["amount_cents"]
        cash_delta(
            tx,
            row["user_id"],
            0 if success else amount,
            -amount,
            "generation_settle" if success else "generation_release",
            status + ":" + row["id"],
            ref=row["generation_id"] or row["id"],
        )
        if not success:
            for allocation in tx.execute(
                "SELECT * FROM cash_allocations WHERE charge_id=?", (row["id"],)
            ).fetchall():
                tx.execute(
                    "UPDATE cash_lots SET remaining_cents=remaining_cents+? WHERE order_id=? AND EXISTS(SELECT 1 FROM payment_orders o WHERE o.id=cash_lots.order_id AND o.status IN ('paid','partially_refunded'))",
                    (allocation["amount_cents"], allocation["order_id"]),
                )


def release_item(tx, item_id):
    row = tx.execute(
        "SELECT * FROM generation_charges WHERE item_id=? AND generation_id IS NULL AND status='reserved' FOR UPDATE",
        (item_id,),
    ).fetchone()
    if row:
        finish_reservation(tx, row)


def release_abandoned_quotes(db, uid):
    """Unsubmitted browser slots expire; accepted attempts and canvas jobs do not."""
    with db.transaction() as tx:
        lock_user(tx, uid)
        rows = tx.execute(
            "SELECT c.* FROM generation_charges c JOIN generation_quotes q ON q.id=c.quote_id WHERE c.user_id=? AND c.status='reserved' AND c.generation_id IS NULL AND c.item_id IS NULL AND q.expires_at<now() FOR UPDATE OF c",
            (uid,),
        ).fetchall()
        for row in rows:
            finish_reservation(tx, row)


def account_summary(tx, uid):
    wallet = tx.execute(
        "SELECT balance FROM wallets WHERE user_id=?", (uid,)
    ).fetchone()
    return {
        "cash": cash(tx, uid),
        "points": int(wallet[0]) if wallet else 0,
        "freeQuota": [
            {k: v for k, v in quota(tx, uid, r[0]).items() if k != "sources"}
            for r in tx.execute(
                "SELECT resolution FROM generation_quota_policy UNION SELECT resolution FROM generation_quota_grants WHERE user_id=? ORDER BY resolution",
                (uid,),
            ).fetchall()
        ],
        "specs": specs(tx),
    }


def admin_required(user):
    if not user or user.get("role") != "admin":
        raise error("需要管理员权限", "forbidden", 403)


def reconcile(tx):
    cash_rows = tx.execute(
        "SELECT a.user_id,a.balance_cents,a.held_cents,COALESCE(e.balance,0) ledger_balance,COALESCE(e.held,0) ledger_held FROM cash_accounts a LEFT JOIN (SELECT user_id,sum(delta_cents) balance,sum(held_delta_cents) held FROM cash_entries GROUP BY user_id) e ON e.user_id=a.user_id WHERE a.balance_cents<>COALESCE(e.balance,0) OR a.held_cents<>COALESCE(e.held,0)"
    ).fetchall()
    point_rows = tx.execute(
        "SELECT w.user_id,w.balance,COALESCE(l.units,0) ledger_balance FROM wallets w LEFT JOIN (SELECT user_id,sum(delta) units FROM ledgers GROUP BY user_id) l ON l.user_id=w.user_id WHERE w.balance<>COALESCE(l.units,0)"
    ).fetchall()
    held_rows = tx.execute(
        "WITH charge AS (SELECT user_id,sum(amount_cents) units FROM generation_charges WHERE status='reserved' GROUP BY user_id), refund AS (SELECT r.user_id,sum(r.amount_cents) units FROM billing_refund_requests r JOIN payment_orders o ON o.id=r.order_id WHERE o.purpose='cash' AND r.status IN ('pending','processing','unknown') GROUP BY r.user_id) SELECT a.user_id,a.held_cents,COALESCE(c.units,0)+COALESCE(r.units,0) expected FROM cash_accounts a LEFT JOIN charge c ON c.user_id=a.user_id LEFT JOIN refund r ON r.user_id=a.user_id WHERE a.held_cents<>COALESCE(c.units,0)+COALESCE(r.units,0)"
    ).fetchall()
    return {
        "ok": not (cash_rows or point_rows or held_rows),
        "cashMismatches": [dict(r) for r in cash_rows],
        "pointsMismatches": [dict(r) for r in point_rows],
        "holdMismatches": [dict(r) for r in held_rows],
    }


def audit(tx, user, action, details):
    from .services import record_audit_log

    record_audit_log(
        tx,
        user,
        action,
        "economy",
        "configuration",
        reason=str(details.get("reason") or action),
        details=details,
    )


def admin_action(db, user, body):
    admin_required(user)
    action = body.get("action")
    if action != "base-preview" and not str(body.get("reason") or "").strip():
        raise error("账务调整必须填写原因")
    with db.transaction() as tx:
        if action == "point-prices":
            kind = body.get("kind")
            values = body.get("options")
            if (
                kind not in ("topic", "asset")
                or not isinstance(values, list)
                or not values
                or len(values) > 20
            ):
                raise error("积分价格档位无效")
            values = sorted(set(integer(x, 0, 500) for x in values))
            if 0 not in values:
                values.insert(0, 0)
            tx.execute(
                "UPDATE point_price_options SET options_json=?::jsonb WHERE kind=?",
                (json.dumps(values), kind),
            )
        elif action == "spec":
            sid = str(body.get("id") or "")
            if not sid or len(sid) > 80:
                raise error("请输入规格编号")
            sizes = body.get("sizes")
            if not isinstance(sizes, dict) or not sizes:
                raise error("规格必须定义实际像素")
            import re

            if any(
                not re.fullmatch(r"[0-9.]+:[0-9.]+", str(k))
                or not re.fullmatch(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}", str(v))
                for k, v in sizes.items()
            ):
                raise error("比例或像素规格格式无效")
            price = body.get("priceCents")
            if price is not None:
                integer(price, 1)
            cost = body.get("costCents")
            if cost is not None:
                integer(cost)
            resolution = str(body.get("resolution") or "").lower()
            if (
                resolution not in ("1k", "2k", "4k")
                or not str(body.get("model") or "").strip()
            ):
                raise error("请设置模型和有效分辨率档位")
            lower, upper = {"1k": (512, 1536), "2k": (1537, 3072), "4k": (3073, 6144)}[
                resolution
            ]
            for ratio, size in sizes.items():
                width, height = map(int, size.split("x"))
                rw, rh = map(float, ratio.split(":"))
                if (
                    rh <= 0
                    or rw <= 0
                    or not lower <= max(width, height) <= upper
                    or abs(width / height - rw / rh) > 0.04
                ):
                    raise error("实际像素必须匹配分辨率档位与比例")
            tx.execute(
                "INSERT INTO generation_specs(id,name,model,resolution,quality,sizes_json,price_cents,cost_cents,enabled,verified) VALUES(?,?,?,?,?,?::jsonb,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,model=excluded.model,resolution=excluded.resolution,quality=excluded.quality,sizes_json=excluded.sizes_json,price_cents=excluded.price_cents,cost_cents=excluded.cost_cents,enabled=excluded.enabled,verified=excluded.verified,version=generation_specs.version+1",
                (
                    sid,
                    str(body.get("name") or sid),
                    str(body["model"]),
                    resolution,
                    str(body.get("quality") or "auto"),
                    json.dumps(sizes),
                    price,
                    cost,
                    body.get("enabled") is True,
                    body.get("verified") is True,
                ),
            )
        elif action in ("base-preview", "base"):
            units = integer(body.get("units"), maximum=10000)
            resolution = str(body.get("resolution") or "1k")
            if resolution not in ("1k", "2k", "4k"):
                raise error("免费额度规格无效")
            old = tx.execute(
                "SELECT base_units FROM generation_quota_policy WHERE resolution=?",
                (resolution,),
            ).fetchone()
            affected = tx.execute(
                "SELECT count(*) FROM users WHERE status='active'"
            ).fetchone()[0]
            preview = {
                "oldUnits": old[0] if old else 0,
                "newUnits": units,
                "affectedUsers": affected,
                "resolution": resolution,
            }
            token = hashlib.sha256(
                json.dumps(preview, sort_keys=True).encode()
            ).hexdigest()
            if action == "base-preview":
                return {"ok": True, **preview, "confirmation": token}
            if body.get("confirmation") != token:
                raise error("请先预览全员额度调整影响", "preview_required", 409)
            tx.execute(
                "INSERT INTO generation_quota_policy(resolution,base_units) VALUES(?,?) ON CONFLICT(resolution) DO UPDATE SET base_units=excluded.base_units,version=generation_quota_policy.version+1",
                (resolution, units),
            )
        elif action == "grant":
            units = integer(body.get("units"), 1, 10000)
            reason = str(body.get("reason") or "").strip()
            key = str(body.get("requestId") or "")
            if not reason or not key or len(key) > 120:
                raise error("赠送必须填写原因和请求编号")
            ids = body.get("userIds")
            group = body.get("group")
            if group == "all":
                ids = [
                    r[0]
                    for r in tx.execute(
                        "SELECT id FROM users WHERE status='active' ORDER BY id"
                    ).fetchall()
                ]
            elif group in ("user", "admin", "moderator", "reviewer"):
                ids = [
                    r[0]
                    for r in tx.execute(
                        "SELECT id FROM users WHERE status='active' AND role=? ORDER BY id",
                        (group,),
                    ).fetchall()
                ]
            if not isinstance(ids, list) or not ids:
                raise error("请选择赠送对象")
            resolution = str(body.get("resolution") or "1k")
            if resolution not in ("1k", "2k", "4k"):
                raise error("赠送规格无效")
            for uid in sorted(set(integer(x, 1) for x in ids)):
                lock_user(tx, uid)
                previous = tx.execute(
                    "SELECT units,resolution,reason,expires_at FROM generation_quota_grants WHERE user_id=? AND event_key=?",
                    (uid, key),
                ).fetchone()
                if previous and (
                    previous["units"] != units
                    or previous["resolution"] != resolution
                    or previous["reason"] != reason
                ):
                    raise error("请求编号已用于另一笔赠送", "request_conflict", 409)
                tx.execute(
                    "INSERT INTO generation_quota_grants(id,user_id,resolution,units,event_key,reason,actor_id,expires_at) VALUES(?,?,?,?,?,?,?,?::timestamptz) ON CONFLICT(user_id,event_key) DO NOTHING",
                    (
                        "gift_" + uuid.uuid4().hex,
                        uid,
                        resolution,
                        units,
                        key,
                        reason,
                        user["id"],
                        body.get("expiresAt") or None,
                    ),
                )
        elif action == "revoke":
            grant = tx.execute(
                "SELECT * FROM generation_quota_grants WHERE id=?",
                (body.get("grantId"),),
            ).fetchone()
            if not grant:
                raise error("赠送记录不存在")
            lock_user(tx, grant["user_id"])
            if not str(body.get("reason") or "").strip():
                raise error("撤回必须填写原因")
            tx.execute(
                "UPDATE generation_quota_grants SET revoked_at=now() WHERE id=?",
                (grant["id"],),
            )
        else:
            raise error("未知的账务管理操作")
        audit(tx, user, "economy_" + action, body)
    return {"ok": True}
