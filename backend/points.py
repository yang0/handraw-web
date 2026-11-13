"""Point provenance, capped contribution rewards and delayed creator settlements."""

from __future__ import annotations

from .economy import error


def track_delta(tx, uid, ledger_id, delta, kind, ref_type, ref_id):
    """Called under the locked points wallet, in the same transaction as its ledger."""
    if delta > 0:
        # Refund restores consumed lots rather than turning gifts into bought points.
        if kind in ("unlock_refund", "refund") and ref_type in ("asset", "topic"):
            original = tx.execute(
                "SELECT id FROM ledgers WHERE user_id=? AND kind='unlock_spend' AND ref_type=? AND ref_id=? ORDER BY id DESC LIMIT 1",
                (uid, ref_type, ref_id),
            ).fetchone()
            if original:
                cutover = tx.execute(
                    "SELECT legacy_ledger_id FROM economy_cutover_state WHERE id=1"
                ).fetchone()
                historical = bool(cutover and original[0] <= cutover[0])
                has_allocations = tx.execute(
                    "SELECT 1 FROM point_allocations WHERE ledger_id=? LIMIT 1",
                    (original[0],),
                ).fetchone()
                if has_allocations or not historical:
                    restore(tx, original[0], delta)
                    return
                # Pre-launch legacy points were not real cash purchases. Their
                # historic unlock refunds restore earned points, never principal.
        balance = tx.execute(
            "SELECT balance FROM wallets WHERE user_id=?", (uid,)
        ).fetchone()[0]
        available = max(0, balance) - max(0, balance - delta)
        tx.execute(
            "INSERT INTO point_lots(user_id,source_key,source_kind,payment_order_id,original_units,remaining_units) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (
                uid,
                "ledger:" + str(ledger_id),
                "purchased" if kind == "recharge" else "earned",
                ref_id if kind == "recharge" and ref_type == "payment_order" else None,
                delta,
                available,
            ),
        )
    elif delta < 0:
        needed = -delta
        priority = (
            "(payment_order_id=?) DESC NULLS LAST,"
            if kind == "recharge_refund" and ref_type == "payment_order"
            else ""
        )
        lots = tx.execute(
            "SELECT * FROM point_lots WHERE user_id=? AND remaining_units>0 ORDER BY "
            + priority
            + "(source_kind='purchased'),id FOR UPDATE",
            (uid, ref_id) if priority else (uid,),
        ).fetchall()
        # Preserve old internal balances as earned points, never cash.
        total = sum(r["remaining_units"] for r in lots)
        wallet = (
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (uid,)
            ).fetchone()[0]
            - delta
        )
        if wallet > total:
            row = tx.execute(
                "INSERT INTO point_lots(user_id,source_key,source_kind,original_units,remaining_units) VALUES(?,?,'legacy',?,?) RETURNING *",
                (uid, "legacy:" + str(ledger_id), wallet - total, wallet - total),
            ).fetchone()
            lots.insert(0, row)
        for row in lots:
            amount = min(needed, row["remaining_units"])
            if not amount:
                break
            tx.execute(
                "UPDATE point_lots SET remaining_units=remaining_units-? WHERE id=?",
                (amount, row["id"]),
            )
            tx.execute(
                "INSERT INTO point_allocations(ledger_id,lot_id,units) VALUES(?,?,?)",
                (ledger_id, row["id"], amount),
            )
            needed -= amount
        # Debt from a confirmed reversal is visible in wallets.balance. Future
        # earnings repay it before there is any spendable balance.


def restore(tx, ledger_id, amount):
    remaining = amount
    for row in tx.execute(
        "SELECT * FROM point_allocations WHERE ledger_id=? ORDER BY lot_id FOR UPDATE",
        (ledger_id,),
    ).fetchall():
        units = min(remaining, row["units"] - row["restored_units"])
        if units:
            tx.execute(
                "UPDATE point_lots SET remaining_units=remaining_units+? WHERE id=?",
                (units, row["lot_id"]),
            )
            tx.execute(
                "UPDATE point_allocations SET restored_units=restored_units+? WHERE ledger_id=? AND lot_id=?",
                (units, ledger_id, row["lot_id"]),
            )
            remaining -= units
    if remaining:
        raise error(
            "积分原始消费来源无法核对，请人工复核",
            "points_reconciliation_required",
            409,
        )


def settle_due(db, uid):
    from .services import apply_wallet_delta

    with db.transaction() as tx:
        wallet = tx.execute(
            "SELECT balance,locked FROM wallets WHERE user_id=? FOR UPDATE", (uid,)
        ).fetchone()
        if wallet and wallet["locked"]:
            return
        for row in tx.execute(
            "SELECT * FROM creator_point_earnings WHERE author_id=? AND status='pending' AND available_at<=now() ORDER BY id FOR UPDATE",
            (uid,),
        ).fetchall():
            apply_wallet_delta(
                tx,
                uid,
                row["units"],
                "unlock_royalty",
                "内容解锁积分分成到账",
                event_key="earning:" + str(row["id"]),
                ref_type="unlock",
                ref_id=str(row["unlock_id"]),
            )
            tx.execute(
                "UPDATE creator_point_earnings SET status='settled',settled_at=now() WHERE id=?",
                (row["id"],),
            )


def earning_summary(tx, uid):
    rows = tx.execute(
        "SELECT status,COALESCE(sum(units),0) units FROM creator_point_earnings WHERE author_id=? GROUP BY status",
        (uid,),
    ).fetchall()
    return {r["status"]: int(r["units"]) for r in rows}


REWARDS = {
    "verified": (20, 1),
    "checkin": (1, 20),
    "quality_work": (5, 10),
    "asset": (20, 10),
    "quality_topic": (10, 10),
}


def reward(tx, uid, kind, target, actor=None):
    from .services import apply_wallet_delta, local_today_str

    units, limit = REWARDS[kind]
    tx.execute(
        "SELECT balance FROM wallets WHERE user_id=? FOR UPDATE", (uid,)
    ).fetchone()
    if tx.execute(
        "SELECT 1 FROM contribution_rewards WHERE kind=? AND target_id=?",
        (kind, str(target)),
    ).fetchone():
        return 0
    month = local_today_str()[:7]
    count = tx.execute(
        "SELECT count(*) FROM contribution_rewards WHERE user_id=? AND kind=?"
        + (" AND month=?" if kind != "verified" else ""),
        (uid, kind, month) if kind != "verified" else (uid, kind),
    ).fetchone()[0]
    if count >= limit:
        return 0
    tx.execute(
        "INSERT INTO contribution_rewards(user_id,kind,target_id,month,units,actor_id) VALUES(?,?,?,?,?,?)",
        (uid, kind, str(target), month, units, actor),
    )
    apply_wallet_delta(
        tx,
        uid,
        units,
        "contribution_" + kind,
        "社区有效贡献奖励",
        event_key="contribution:" + kind + ":" + str(target),
        ref_type=kind,
        ref_id=str(target),
        actor_id=actor,
    )
    return units


def admin_reward(db, user, body):
    from .economy import admin_required, audit

    admin_required(user)
    kind = body.get("kind")
    target = str(body.get("targetId") or "")
    if kind not in ("quality_work", "quality_topic"):
        raise error("请选择优质作品或优质教程")
    table = "works" if kind == "quality_work" else "forum_topics"
    with db.transaction() as tx:
        row = tx.execute(
            f"SELECT u.id FROM {table} p JOIN users u ON u.username=p.author_username WHERE p.id=? AND p.status='published'",
            (target,),
        ).fetchone()
        if not row:
            raise error("内容未发布或作者不存在")
        granted = reward(tx, row[0], kind, target, user["id"])
        audit(tx, user, "contribution_reward", {**body, "granted": granted})
    return {"ok": True, "rewarded": granted}


def reverse_earning(tx, unlock_id):
    from .services import apply_wallet_delta

    owner = tx.execute(
        "SELECT author_id FROM creator_point_earnings WHERE unlock_id=? ORDER BY purchase_seq DESC LIMIT 1",
        (unlock_id,),
    ).fetchone()
    if owner:
        tx.execute(
            "SELECT balance FROM wallets WHERE user_id=? FOR UPDATE", (owner[0],)
        ).fetchone()
    earning = tx.execute(
        "SELECT * FROM creator_point_earnings WHERE unlock_id=? ORDER BY purchase_seq DESC LIMIT 1 FOR UPDATE",
        (unlock_id,),
    ).fetchone()
    if earning and earning["status"] != "reversed":
        if earning["status"] == "settled":
            apply_wallet_delta(
                tx,
                earning["author_id"],
                -earning["units"],
                "royalty_reversal",
                "内容解锁退款，冲回作者分成",
                event_key="earning_reversal:" + str(earning["id"]),
                ref_type="unlock",
                ref_id=str(unlock_id),
                allow_negative=True,
            )
        tx.execute(
            "UPDATE creator_point_earnings SET status='reversed' WHERE id=?",
            (earning["id"],),
        )


def validate_price(tx, kind, value):
    row = tx.execute(
        "SELECT options_json FROM point_price_options WHERE kind=?", (kind,)
    ).fetchone()
    if type(value) is not int or not row or value not in row[0]:
        raise error("请选择允许的积分价格档位", "invalid_point_price")
