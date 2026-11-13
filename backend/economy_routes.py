"""HTTP boundary for separate cash, points and generation benefits."""

from __future__ import annotations
from . import economy


def handle_get(handler, path, qs):
    if path not in ("/api/economy", "/api/admin/economy"):
        return False
    user = handler._current_user(required=True)
    from .points import settle_due, earning_summary, reward

    economy.release_abandoned_quotes(handler.db, user["id"])
    settle_due(handler.db, user["id"])
    with handler.db.transaction() as tx:
        if tx.execute(
            "SELECT 1 FROM verified_emails WHERE user_id=?", (user["id"],)
        ).fetchone():
            reward(tx, user["id"], "verified", str(user["id"]))
    tx = handler.db.get_conn()
    result = {
        "ok": True,
        **economy.account_summary(tx, user["id"]),
        "earnings": earning_summary(tx, user["id"]),
    }
    if path.startswith("/api/admin/"):
        economy.admin_required(user)
        result["reconciliation"] = economy.reconcile(tx)
        result["pointPrices"] = {
            r["kind"]: r["options_json"]
            for r in tx.execute("SELECT * FROM point_price_options").fetchall()
        }
        result.update(
            specs=[
                dict(r)
                for r in tx.execute(
                    "SELECT * FROM generation_specs ORDER BY id"
                ).fetchall()
            ],
            policies=[
                dict(r)
                for r in tx.execute(
                    "SELECT * FROM generation_quota_policy ORDER BY resolution"
                ).fetchall()
            ],
            grants=[
                dict(r)
                for r in tx.execute(
                    "SELECT g.*,u.username FROM generation_quota_grants g JOIN users u ON u.id=g.user_id ORDER BY g.created_at DESC LIMIT 100"
                ).fetchall()
            ],
            refunds=[
                dict(r)
                for r in tx.execute(
                    "SELECT r.*,u.username,o.purpose,o.provider FROM billing_refund_requests r JOIN users u ON u.id=r.user_id JOIN payment_orders o ON o.id=r.order_id ORDER BY r.created_at DESC LIMIT 100"
                ).fetchall()
            ],
        )
        # JSON serializers elsewhere use plain values; explicitly format timestamps.
    else:
        result.update(
            cashEntries=[
                {**dict(r), "created_at": r["created_at"].isoformat()}
                for r in tx.execute(
                    "SELECT id,kind,delta_cents,held_delta_cents,balance_after_cents,reason,created_at FROM cash_entries WHERE user_id=? ORDER BY id DESC LIMIT 100",
                    (user["id"],),
                ).fetchall()
            ],
            pointEntries=[
                dict(r)
                for r in tx.execute(
                    "SELECT id,kind,delta,balance_after,reason,created_at FROM ledgers WHERE user_id=? ORDER BY id DESC LIMIT 100",
                    (user["id"],),
                ).fetchall()
            ],
            unlocks=[
                dict(r)
                for r in tx.execute(
                    "SELECT target_type,target_id,cost,status FROM unlocks WHERE user_id=? ORDER BY id DESC LIMIT 100",
                    (user["id"],),
                ).fetchall()
            ],
        )
    import json

    handler._send_json(json.loads(json.dumps(result, default=str)))
    return True


def handle_post(handler, path, body):
    if path not in (
        "/api/studio/quote",
        "/api/admin/economy",
        "/api/admin/economy/reward",
        "/api/billing/refund-requests",
        "/api/admin/economy/refunds",
    ):
        return False
    user = handler._current_user(required=True)
    if path == "/api/studio/quote":
        result = economy.create_quote(handler.db, user, body.get("items"))
    elif path == "/api/admin/economy":
        result = economy.admin_action(handler.db, user, body)
    elif path == "/api/admin/economy/reward":
        from .points import admin_reward

        result = admin_reward(handler.db, user, body)
    elif path == "/api/billing/refund-requests":
        from .billing_refunds import request_refund

        result = request_refund(handler.db, user, body)
    else:
        from .billing_refunds import process_refund

        result = process_refund(handler.db, user, body)
    handler._send_json(result)
    return True
