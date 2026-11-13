"""Unused principal refunds, with durable holds and no blind upstream retries."""

from __future__ import annotations
import json
import uuid
from .economy import error, lock_user, cash_delta, admin_required, audit


def refundable(tx, order):
    if order["purpose"] == "cash":
        row = tx.execute(
            "SELECT remaining_cents FROM cash_lots WHERE order_id=?", (order["id"],)
        ).fetchone()
        return (int(row[0]) if row else 0), 0
    row = tx.execute(
        "SELECT COALESCE(sum(remaining_units),0) FROM point_lots WHERE payment_order_id=?",
        (order["id"],),
    ).fetchone()
    return int(row[0]) * 10, int(row[0])


def request_refund(db, user, body):
    uid = user["id"]
    with db.transaction() as tx:
        lock_user(tx, uid)
        order = tx.execute(
            "SELECT * FROM payment_orders WHERE id=? AND user_id=? FOR UPDATE",
            (body.get("orderId"), uid),
        ).fetchone()
        if not order or order["status"] not in ("paid", "partially_refunded"):
            raise error("此订单暂无可退款款项")
        existing = tx.execute(
            "SELECT * FROM billing_refund_requests WHERE order_id=? AND status IN ('pending','processing','unknown')",
            (order["id"],),
        ).fetchone()
        if existing:
            return {
                "ok": True,
                "refundId": existing["id"],
                "status": existing["status"],
            }
        amount, units = refundable(tx, order)
        if amount <= 0:
            raise error("该订单没有可核实的未消费余额")
        reason = str(body.get("reason") or "退还未消费部分").strip()[:500]
        rid = "refund_" + uuid.uuid4().hex
        if order["purpose"] == "cash":
            cash_delta(
                tx,
                uid,
                -amount,
                amount,
                "refund_hold",
                "refund_hold:" + rid,
                ref=order["id"],
            )
            tx.execute(
                "UPDATE cash_lots SET remaining_cents=remaining_cents-? WHERE order_id=?",
                (amount, order["id"]),
            )
        else:
            # Remove exactly the original bought lots, never unrelated earned points.
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=? FOR UPDATE", (uid,)
            ).fetchone()
            tx.execute(
                "UPDATE point_lots SET remaining_units=0 WHERE payment_order_id=?",
                (order["id"],),
            )
            tx.execute(
                "UPDATE wallets SET balance=balance-? WHERE user_id=?", (units, uid)
            )
            tx.execute(
                "INSERT INTO ledgers(user_id,delta,balance_after,kind,event_key,reason,ref_type,ref_id,created_at) SELECT user_id,?,balance,'purchase_refund_hold',?,?, 'payment_order',?,CURRENT_TIMESTAMP::text FROM wallets WHERE user_id=?",
                (-units, "refund_hold:" + rid, reason, order["id"], uid),
            )
        tx.execute(
            "INSERT INTO billing_refund_requests(id,user_id,order_id,reason,amount_cents,units) VALUES(?,?,?,?,?,?)",
            (rid, uid, order["id"], reason, amount, units),
        )
    return {"ok": True, "refundId": rid, "amountCents": amount, "status": "pending"}


def process_refund(db, user, body):
    admin_required(user)
    rid = str(body.get("refundId") or "")
    if body.get("action") == "reconcile":
        return reconcile_refund(db, user, body)
    from .billing import load_payment_config, xorpay_sign, _xorpay_api_request

    with db.transaction() as tx:
        owner = tx.execute(
            "SELECT user_id FROM billing_refund_requests WHERE id=?", (rid,)
        ).fetchone()
        if not owner:
            raise error("退款申请不存在")
        lock_user(tx, owner[0])
        req = tx.execute(
            "SELECT * FROM billing_refund_requests WHERE id=? FOR UPDATE", (rid,)
        ).fetchone()
        if not req:
            raise error("退款申请不存在")
        if req["status"] != "pending":
            return {"ok": True, "status": req["status"], "resubmitted": False}
        order = tx.execute(
            "SELECT * FROM payment_orders WHERE id=?", (req["order_id"],)
        ).fetchone()
        if order["provider"] != "xorpay":
            raise error(
                "当前自动原路退款仅支持XorPay；其他渠道需核对提供方的退款记录",
                "refund_provider_unsupported",
                409,
            )
        cfg = load_payment_config()
        secret = str(cfg.get("app_secret") or "").strip()
        if not secret or not order["provider_order_id"]:
            raise error(
                "退款渠道尚未配置完成或缺少支付平台订单号", "refund_not_configured", 503
            )
        tx.execute(
            "UPDATE billing_refund_requests SET status='processing' WHERE id=?", (rid,)
        )
        audit(
            tx,
            user,
            "refund_start",
            {"refundId": rid, "amountCents": req["amount_cents"]},
        )
    price = f"{req['amount_cents'] // 100}.{req['amount_cents'] % 100:02d}"
    db.release_request_connection()
    try:
        # XorPay has no documented idempotency key. Never retry this POST on a
        # transport error: its outcome is unknown and needs merchant reconciliation.
        result = _xorpay_api_request(
            "POST",
            "/api/refund/" + str(order["provider_order_id"]),
            {
                "price": price,
                "sign": xorpay_sign(price, secret),
            },
            api_base=str(cfg.get("api_base") or "https://xorpay.com"),
            retry=False,
        )
    except Exception:
        with db.transaction() as tx:
            tx.execute(
                "UPDATE billing_refund_requests SET status='unknown' WHERE id=? AND status='processing'",
                (rid,),
            )
        raise error(
            "退款请求结果未知，已保留冻结，请管理员核对支付平台，勿重复退款",
            "refund_unknown",
            409,
        )
    with db.transaction() as tx:
        lock_user(tx, req["user_id"])
        current = tx.execute(
            "SELECT * FROM billing_refund_requests WHERE id=? FOR UPDATE", (rid,)
        ).fetchone()
        # A provider callback or merchant reconciliation may have completed this
        # hold while the HTTP request was in flight. Its terminal decision wins.
        if current["status"] != "processing":
            return {"ok": True, "status": current["status"], "resubmitted": False}
        if result.get("status") not in (
            "ok",
            "order_error",
            "price_error",
            "sign_error",
        ):
            tx.execute(
                "UPDATE billing_refund_requests SET status='unknown',provider_result=?::jsonb WHERE id=?",
                (json.dumps(result), rid),
            )
            audit(tx, user, "refund_unknown", {"refundId": rid})
            return {"ok": True, "status": "unknown", "resubmitted": False}
        status = "completed" if result.get("status") == "ok" else "rejected"
        tx.execute(
            "UPDATE billing_refund_requests SET status=?,provider_result=?::jsonb WHERE id=?",
            (status, json.dumps(result), rid),
        )
        if order["purpose"] == "cash":
            amount = req["amount_cents"]
            cash_delta(
                tx,
                req["user_id"],
                0 if status == "completed" else amount,
                -amount,
                "refund_complete" if status == "completed" else "refund_release",
                status + ":" + rid,
                ref=order["id"],
            )
            if status != "completed":
                tx.execute(
                    "UPDATE cash_lots SET remaining_cents=remaining_cents+? WHERE order_id=?",
                    (amount, order["id"]),
                )
        elif status != "completed":
            from .services import apply_wallet_delta

            apply_wallet_delta(
                tx,
                req["user_id"],
                req["units"],
                "recharge",
                "退款未执行，恢复购买积分",
                event_key="refund_restore:" + rid,
                ref_type="payment_order",
                ref_id=order["id"],
            )
        if status == "completed":
            tx.execute(
                "UPDATE payment_orders SET status='partially_refunded',updated_at=CURRENT_TIMESTAMP::text WHERE id=?",
                (order["id"],),
            )
        audit(tx, user, "refund_" + status, {"refundId": rid})
    return {"ok": True, "status": status}


def reconcile_refund(db, user, body):
    """Record a merchant-verified outcome; never submit the refund again."""
    admin_required(user)
    status = body.get("outcome")
    evidence = str(body.get("providerReference") or "").strip()
    reason = str(body.get("reason") or "").strip()
    if status not in ("completed", "rejected") or not evidence or not reason:
        raise error("请填写支付平台核对凭据、原因和明确退款结果")
    with db.transaction() as tx:
        owner = tx.execute(
            "SELECT user_id FROM billing_refund_requests WHERE id=?",
            (body.get("refundId"),),
        ).fetchone()
        if not owner:
            raise error("退款申请不存在")
        lock_user(tx, owner[0])
        req = tx.execute(
            "SELECT * FROM billing_refund_requests WHERE id=? FOR UPDATE",
            (body["refundId"],),
        ).fetchone()
        if req["status"] in ("completed", "rejected"):
            return {"ok": True, "status": req["status"], "idempotent": True}
        if req["status"] not in ("pending", "unknown", "processing"):
            raise error("只有待处理或结果未知的退款可以核对")
        order = tx.execute(
            "SELECT * FROM payment_orders WHERE id=? FOR UPDATE", (req["order_id"],)
        ).fetchone()
        rid = req["id"]
        if order["purpose"] == "cash":
            cash_delta(
                tx,
                req["user_id"],
                0 if status == "completed" else req["amount_cents"],
                -req["amount_cents"],
                "refund_reconciled",
                status + ":" + rid,
                ref=order["id"],
            )
            if status == "rejected":
                tx.execute(
                    "UPDATE cash_lots SET remaining_cents=remaining_cents+? WHERE order_id=?",
                    (req["amount_cents"], order["id"]),
                )
        elif status == "rejected":
            from .services import apply_wallet_delta

            apply_wallet_delta(
                tx,
                req["user_id"],
                req["units"],
                "recharge",
                "平台核对未退款，恢复购买积分",
                event_key="refund_restore:" + rid,
                ref_type="payment_order",
                ref_id=order["id"],
            )
        tx.execute(
            "UPDATE billing_refund_requests SET status=?,provider_result=?::jsonb WHERE id=?",
            (
                status,
                json.dumps(
                    {
                        "providerReference": evidence,
                        "reason": reason,
                        "reconciledBy": user["id"],
                    }
                ),
                rid,
            ),
        )
        if status == "completed":
            tx.execute(
                "UPDATE payment_orders SET status='partially_refunded',updated_at=CURRENT_TIMESTAMP::text WHERE id=?",
                (order["id"],),
            )
        audit(tx, user, "refund_reconcile", {**body, "resubmitted": False})
    return {"ok": True, "status": status, "resubmitted": False}


def apply_provider_refund(tx, order, provider_id):
    """A trusted full refund closes outstanding refund holds and reverses only net principal."""
    uid = order["user_id"]
    lock_user(tx, uid)
    tx.execute(
        "SELECT balance FROM wallets WHERE user_id=? FOR UPDATE", (uid,)
    ).fetchone()
    requests = tx.execute(
        "SELECT * FROM billing_refund_requests WHERE order_id=? ORDER BY id FOR UPDATE",
        (order["id"],),
    ).fetchall()
    completed = sum(r["amount_cents"] for r in requests if r["status"] == "completed")
    open_requests = [
        r for r in requests if r["status"] in ("pending", "processing", "unknown")
    ]
    held = sum(r["amount_cents"] for r in open_requests)
    net = max(0, int(order["amount_cents"]) - completed - held)
    if order["purpose"] == "cash":
        state, applied = cash_delta(
            tx,
            uid,
            -net,
            -held,
            "provider_refund",
            "provider_refund:" + order["id"],
            ref=order["id"],
            debt=True,
        )
        tx.execute(
            "UPDATE cash_lots SET remaining_cents=0 WHERE order_id=?", (order["id"],)
        )
        balance = state["balanceCents"]
    else:
        from .services import apply_wallet_delta

        completed_units = sum(
            r["units"] for r in requests if r["status"] == "completed"
        )
        held_units = sum(r["units"] for r in open_requests)
        units = max(0, int(order["credits"]) - completed_units - held_units)
        balance, applied = apply_wallet_delta(
            tx,
            uid,
            -units,
            "recharge_refund",
            "支付提供方确认退款",
            event_key="provider_refund:" + order["id"],
            ref_type="payment_order",
            ref_id=order["id"],
            allow_negative=True,
        )
    if applied:
        for req in open_requests:
            tx.execute(
                "UPDATE billing_refund_requests SET status='completed',provider_result=?::jsonb WHERE id=?",
                (json.dumps({"fullProviderRefund": provider_id}), req["id"]),
            )
    return balance, applied
