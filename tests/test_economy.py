"""Cash/points separation, entitlement fencing and terminal accounting on real PG."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from backend import economy
from backend.services import (
    register_user,
    ServiceError,
    prepare_cloud_generation,
    complete_cloud_generation,
    refund_failed_cloud_generation,
    apply_wallet_delta,
)
from tests.postgres_support import open_isolated_postgres


class EconomyTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self, seed=True)
        self.user, _ = register_user(self.db, "economy_user", "FixturePass123!")
        self.uid = self.user["id"]
        self.db.get_conn().execute(
            "UPDATE generation_specs SET verified=true,price_cents=25,cost_cents=10"
        )

    def quote(self, count=1, **spec):
        return economy.create_quote(
            self.db, self.user, [{"ratio": "3:4", **spec}] * count
        )

    def test_registration_has_ten_lifetime_1k_and_no_cash_from_points(self):
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["remaining"], 10)
        with self.db.transaction() as tx:
            apply_wallet_delta(tx, self.uid, 200, "admin_adjust", "internal points")
        self.assertEqual(economy.cash(self.db.get_conn(), self.uid)["balanceCents"], 0)
        q = self.quote(11)
        self.assertEqual(
            (q["freeCount"], q["totalCents"], q["affordable"]), (10, 25, False)
        )

    def test_two_concurrent_quotes_cannot_spend_last_free_slot(self):
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=1")
        quotes = [self.quote(), self.quote()]

        def run(q):
            try:
                with self.db.transaction() as tx:
                    economy.reserve_quote(tx, self.uid, q["quoteId"], q["quoteId"])
                return "accepted"
            except ServiceError as exc:
                return exc.code
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(2) as pool:
            result = list(pool.map(run, quotes))
        self.assertCountEqual(result, ["accepted", "quota_changed"])

    def test_concurrent_paid_quotes_cannot_overdraw_cash(self):
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=0")
        with self.db.transaction() as tx:
            economy.cash_delta(tx, self.uid, 25, 0, "recharge", "limited-cash")
        quotes = [self.quote(), self.quote()]

        def accept(q):
            try:
                with self.db.transaction() as tx:
                    economy.reserve_quote(tx, self.uid, q["quoteId"], q["quoteId"])
                return "accepted"
            except ServiceError as exc:
                return exc.code
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(accept, quotes))
        self.assertCountEqual(results, ["accepted", "insufficient_cash"])
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 0, "heldCents": 25},
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT count(*) FROM generation_charges")
            .fetchone()[0],
            1,
        )

    def test_ledger_entries_cannot_be_rewritten(self):
        from psycopg.errors import RaiseException

        with self.db.transaction() as tx:
            economy.cash_delta(tx, self.uid, 25, 0, "recharge", "immutable-cash")
            apply_wallet_delta(tx, self.uid, 5, "admin_adjust", "immutable points")
        for table in ("cash_entries", "ledgers"):
            for operation in (
                f"UPDATE {table} SET reason='changed'",
                f"DELETE FROM {table}",
            ):
                with self.assertRaises(RaiseException):
                    with self.db.transaction() as tx:
                        tx.execute(operation)
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_hold_settle_release_partial_and_duplicates(self):
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=1")
        with self.db.transaction() as tx:
            economy.cash_delta(tx, self.uid, 100, 0, "recharge", "test_payment")
        q = self.quote(3)
        with self.db.transaction() as tx:
            economy.reserve_quote(tx, self.uid, q["quoteId"], "batch")
            economy.reserve_quote(tx, self.uid, q["quoteId"], "batch")
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 50, "heldCents": 50},
        )
        rows = (
            self.db.get_conn()
            .execute("SELECT * FROM generation_charges ORDER BY position")
            .fetchall()
        )
        with self.db.transaction() as tx:
            economy.finish_reservation(tx, rows[0], success=True)
            economy.finish_reservation(tx, rows[1], success=True)
            economy.finish_reservation(tx, rows[2], success=False)
            economy.finish_reservation(tx, rows[2], success=False)
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 75, "heldCents": 0},
        )

    def test_actual_generation_only_settles_on_saved_result(self):
        q = self.quote()
        body = {
            "prompt": "一只猫",
            "requestId": "generation-test",
            "quoteId": q["quoteId"],
            "confirmCost": True,
        }
        result = prepare_cloud_generation(self.db, self.user, body)
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["held"], 1)
        complete_cloud_generation(
            self.db,
            result["genId"],
            "task",
            ["/images/poster-demo-autumn-equinox.webp"],
        )
        complete_cloud_generation(
            self.db, result["genId"], "task", ["/images/other.webp"]
        )
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["used"], 1)
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT balance FROM wallets WHERE user_id=?", (self.uid,))
            .fetchone()[0],
            0,
        )

    def test_failure_releases_once_and_price_changes_fence_unaccepted_quotes(self):
        q = self.quote()
        self.db.get_conn().execute("UPDATE generation_specs SET version=version+1")
        with self.assertRaisesRegex(ServiceError, "更新"):
            with self.db.transaction() as tx:
                economy.reserve_quote(tx, self.uid, q["quoteId"], "changed")
        q = self.quote()
        result = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "prompt": "一只猫",
                "requestId": "fails",
                "quoteId": q["quoteId"],
                "confirmCost": True,
            },
        )
        refund_failed_cloud_generation(self.db, result["genId"], "upstream failed")
        refund_failed_cloud_generation(self.db, result["genId"], "duplicate")
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["remaining"], 10)

    def test_2k_never_uses_1k_free_allowance(self):
        self.db.get_conn().execute(
            "INSERT INTO generation_specs SELECT 'high-2k','2K',model,'2k',quality,'{\"3:4\":\"2304x3072\"}'::jsonb,100,50,1,true,true FROM generation_specs LIMIT 1"
        )
        q = self.quote(specId="high-2k")
        self.assertEqual((q["freeCount"], q["totalCents"]), (0, 100))

    def test_unconfigured_price_and_unverified_spec_fail_closed(self):
        self.db.get_conn().execute("UPDATE generation_specs SET price_cents=NULL")
        self.assertEqual(self.quote()["totalCents"], 0)
        with self.assertRaises(ServiceError):
            self.quote(11)
        self.db.get_conn().execute("UPDATE generation_specs SET verified=false")
        with self.assertRaises(ServiceError):
            self.quote()

    def test_admin_base_adjustment_and_gift_revoke_keep_inflight(self):
        self.user["role"] = "admin"
        q = self.quote()
        with self.db.transaction() as tx:
            economy.reserve_quote(tx, self.uid, q["quoteId"], "held")
        p = economy.admin_action(
            self.db, self.user, {"action": "base-preview", "units": 0}
        )
        economy.admin_action(
            self.db,
            self.user,
            {
                "action": "base",
                "units": 0,
                "confirmation": p["confirmation"],
                "reason": "Test lower base total",
            },
        )
        body = {
            "action": "grant",
            "units": 2,
            "userIds": [self.uid],
            "reason": "manual gift",
            "requestId": "gift-1",
        }
        economy.admin_action(self.db, self.user, body)
        economy.admin_action(self.db, self.user, body)
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["remaining"], 1)
        gift = (
            self.db.get_conn()
            .execute("SELECT id FROM generation_quota_grants")
            .fetchone()[0]
        )
        economy.admin_action(
            self.db,
            self.user,
            {"action": "revoke", "grantId": gift, "reason": "cancel unused"},
        )
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["remaining"], 0)
        row = self.db.get_conn().execute("SELECT * FROM generation_charges").fetchone()
        with self.db.transaction() as tx:
            economy.finish_reservation(tx, row, success=True)
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["used"], 1)
        with self.assertRaisesRegex(ServiceError, "原因"):
            economy.admin_action(
                self.db,
                self.user,
                {"action": "base", "units": 1, "confirmation": p["confirmation"]},
            )

    def test_base_total_adjustments_follow_authorization_formula(self):
        q = self.quote(6)
        with self.db.transaction() as tx:
            economy.reserve_quote(tx, self.uid, q["quoteId"], "six-free")
            for row in tx.execute(
                "SELECT * FROM generation_charges ORDER BY position"
            ).fetchall():
                economy.finish_reservation(tx, row, success=True)
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=20")
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["remaining"], 14)
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=0")
        economy.admin_action(
            self.db,
            {**self.user, "role": "admin"},
            {
                "action": "grant",
                "userIds": [self.uid],
                "units": 8,
                "reason": "new authorized total",
                "requestId": "after-base-lowering",
            },
        )
        state = economy.quota(self.db.get_conn(), self.uid)
        self.assertEqual(
            (state["total"], state["used"], state["held"], state["remaining"]),
            (8, 6, 0, 2),
        )
        self.assertEqual(sum(s["remaining"] for s in state["sources"]), 2)

    def test_expired_or_revoked_gifts_keep_only_accepted_authorization(self):
        economy.admin_action(
            self.db,
            {**self.user, "role": "admin"},
            {
                "action": "grant",
                "userIds": [self.uid],
                "units": 3,
                "reason": "three-gift",
                "requestId": "three-gift",
            },
        )
        q = self.quote(2)
        with self.db.transaction() as tx:
            economy.reserve_quote(tx, self.uid, q["quoteId"], "gift-batch")
            rows = tx.execute(
                "SELECT * FROM generation_charges ORDER BY position"
            ).fetchall()
            self.assertTrue(all(r["quota_source"] != "base" for r in rows))
            economy.finish_reservation(tx, rows[0], success=True)
        for statement in (
            "UPDATE generation_quota_grants SET expires_at=now()-interval '1 second'",
            "UPDATE generation_quota_grants SET revoked_at=now()",
        ):
            self.db.get_conn().execute(statement)
            state = economy.quota(self.db.get_conn(), self.uid)
            self.assertEqual(
                (state["total"], state["used"], state["held"], state["remaining"]),
                (12, 1, 1, 10),
            )
        with self.db.transaction() as tx:
            economy.finish_reservation(tx, rows[1], success=False)
        state = economy.quota(self.db.get_conn(), self.uid)
        self.assertEqual(
            (state["total"], state["used"], state["held"], state["remaining"]),
            (11, 1, 0, 10),
        )


class PointsAndPaymentsTests(unittest.TestCase):
    setUp = EconomyTests.setUp

    def paid_order(self, purpose="cash", key="order-test"):
        from backend.billing import _settle_paid_order_tx

        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO payment_orders(id,user_id,pack_id,credits,amount_cents,currency,created_at,updated_at,provider,purpose) VALUES(?,?,'fixture',?,1000,'CNY',CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text,'xorpay',?)",
                (key, self.uid, 100 if purpose == "points" else 0, purpose),
            )
            _, _, applied = _settle_paid_order_tx(
                tx, order_id=key, provider_order_id="provider-" + key, provider="xorpay"
            )
            self.assertTrue(applied)
        return key

    def test_payment_purpose_and_duplicate_callbacks(self):
        from backend.billing import _settle_paid_order_tx

        self.paid_order()
        self.paid_order("points", "points-test")
        with self.db.transaction() as tx:
            for key in ("order-test", "points-test"):
                self.assertFalse(
                    _settle_paid_order_tx(
                        tx,
                        order_id=key,
                        provider_order_id="provider-" + key,
                        provider="xorpay",
                    )[2]
                )
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid)["balanceCents"], 1000
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT balance FROM wallets WHERE user_id=?", (self.uid,))
            .fetchone()[0],
            100,
        )

    def test_full_provider_refund_consumes_pending_hold_without_double_debit(self):
        from backend.billing_refunds import request_refund
        from backend.billing import _refund_order_tx

        self.paid_order()
        refund = request_refund(self.db, self.user, {"orderId": "order-test"})
        with self.db.transaction() as tx:
            _refund_order_tx(
                tx, provider="xorpay", provider_order_id="provider-order-test"
            )
            _refund_order_tx(
                tx, provider="xorpay", provider_order_id="provider-order-test"
            )
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 0, "heldCents": 0},
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT status FROM billing_refund_requests WHERE id=?",
                (refund["refundId"],),
            )
            .fetchone()[0],
            "completed",
        )
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_provider_point_refund_retains_earned_points(self):
        from backend.billing import _refund_order_tx

        self.paid_order("points")
        with self.db.transaction() as tx:
            apply_wallet_delta(tx, self.uid, 20, "admin_adjust", "earned budget")
            _refund_order_tx(
                tx, provider="xorpay", provider_order_id="provider-order-test"
            )
        rows = (
            self.db.get_conn()
            .execute(
                "SELECT source_kind,sum(remaining_units) units FROM point_lots WHERE user_id=? GROUP BY source_kind",
                (self.uid,),
            )
            .fetchall()
        )
        self.assertEqual({r[0]: r[1] for r in rows}, {"earned": 20, "purchased": 0})

    def test_content_refund_after_payment_reversal_does_not_recreate_spendable_lots(
        self,
    ):
        from backend.billing import _refund_order_tx

        self.paid_order("points")
        with self.db.transaction() as tx:
            apply_wallet_delta(
                tx,
                self.uid,
                -30,
                "unlock_spend",
                "content",
                event_key="content-spend",
                ref_type="asset",
                ref_id="REFUND-RESOURCE",
            )
            _refund_order_tx(
                tx, provider="xorpay", provider_order_id="provider-order-test"
            )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT balance FROM wallets WHERE user_id=?", (self.uid,))
            .fetchone()[0],
            -30,
        )
        with self.db.transaction() as tx:
            apply_wallet_delta(
                tx,
                self.uid,
                30,
                "unlock_refund",
                "content refund",
                event_key="content-refund",
                ref_type="asset",
                ref_id="REFUND-RESOURCE",
            )
            self.assertFalse(
                apply_wallet_delta(
                    tx,
                    self.uid,
                    30,
                    "unlock_refund",
                    "duplicate",
                    event_key="content-refund",
                    ref_type="asset",
                    ref_id="REFUND-RESOURCE",
                )[1]
            )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT balance FROM wallets WHERE user_id=?", (self.uid,))
            .fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT sum(remaining_units) FROM point_lots WHERE user_id=?",
                (self.uid,),
            )
            .fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT sum(restored_units) FROM point_allocations a JOIN ledgers l ON l.id=a.ledger_id WHERE l.event_key='content-spend'"
            )
            .fetchone()[0],
            30,
        )

    def test_content_refund_restores_only_surplus_after_partial_debt_repayment(self):
        from backend.billing import _refund_order_tx

        self.paid_order("points")
        with self.db.transaction() as tx:
            apply_wallet_delta(
                tx,
                self.uid,
                -30,
                "unlock_spend",
                "content",
                ref_type="asset",
                ref_id="PARTIAL-REFUND",
            )
            _refund_order_tx(
                tx, provider="xorpay", provider_order_id="provider-order-test"
            )
            apply_wallet_delta(
                tx, self.uid, 20, "admin_adjust", "earned after reversal"
            )
            apply_wallet_delta(
                tx,
                self.uid,
                30,
                "unlock_refund",
                "content refund",
                ref_type="asset",
                ref_id="PARTIAL-REFUND",
            )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT balance FROM wallets WHERE user_id=?", (self.uid,))
            .fetchone()[0],
            20,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT sum(remaining_units) FROM point_lots WHERE user_id=?",
                (self.uid,),
            )
            .fetchone()[0],
            20,
        )

    def reversed_cash_generation(self):
        from backend.billing import _refund_order_tx

        self.paid_order()
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=0")
        quote = economy.create_quote(self.db, self.user, [{"ratio": "3:4"}])
        result = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "prompt": "cash refund race",
                "requestId": "reversed-cash-task",
                "quoteId": quote["quoteId"],
                "confirmCost": True,
            },
        )
        with self.db.transaction() as tx:
            _refund_order_tx(
                tx, provider="xorpay", provider_order_id="provider-order-test"
            )
        return result["genId"]

    def test_accepted_generation_can_settle_after_provider_reversal(self):
        gid = self.reversed_cash_generation()
        complete_cloud_generation(
            self.db, gid, "upstream-task", ["/images/poster-demo-autumn-equinox.webp"]
        )
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": -25, "heldCents": 0},
        )
        self.paid_order(key="after-debt")
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid)["balanceCents"], 975
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT remaining_cents FROM cash_lots WHERE order_id='after-debt'"
            )
            .fetchone()[0],
            975,
        )
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_failed_generation_clears_hold_after_provider_reversal(self):
        gid = self.reversed_cash_generation()
        refund_failed_cloud_generation(self.db, gid, "confirmed failure")
        refund_failed_cloud_generation(self.db, gid, "duplicate failure")
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 0, "heldCents": 0},
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT remaining_cents FROM cash_lots WHERE order_id='order-test'"
            )
            .fetchone()[0],
            0,
        )
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_recharge_that_only_partially_repays_cash_debt_has_no_refundable_principal(
        self,
    ):
        from backend.billing_refunds import request_refund

        with self.db.transaction() as tx:
            economy.cash_delta(
                tx,
                self.uid,
                -1500,
                0,
                "provider_refund",
                "reversed-prior-income",
                debt=True,
            )
        self.paid_order(key="partial-debt")
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid)["balanceCents"], -500
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT remaining_cents FROM cash_lots WHERE order_id='partial-debt'"
            )
            .fetchone()[0],
            0,
        )
        with self.assertRaisesRegex(ServiceError, "未消费余额"):
            request_refund(self.db, self.user, {"orderId": "partial-debt"})
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_unsubmitted_quote_expires_but_accepted_attempt_stays_reserved(self):
        first = economy.create_quote(
            self.db, self.user, [{"ratio": "3:4"}, {"ratio": "3:4"}]
        )
        generation = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "prompt": "cat",
                "quoteId": first["quoteId"],
                "requestId": "one-accepted",
                "confirmCost": True,
            },
        )
        self.db.get_conn().execute(
            "UPDATE generation_quotes SET expires_at=now()-interval '1 second'"
        )
        economy.release_abandoned_quotes(self.db, self.uid)
        rows = (
            self.db.get_conn()
            .execute("SELECT status FROM generation_charges ORDER BY position")
            .fetchall()
        )
        self.assertEqual([r[0] for r in rows], ["reserved", "released"])
        refund_failed_cloud_generation(
            self.db, generation["genId"], "confirmed failure"
        )
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["remaining"], 10)

    def test_additive_upgrade_reapply_preserves_point_sources(self):
        from ops.upgrade_economy import upgrade
        from unittest.mock import patch
        import os

        self.paid_order("points")
        before = (
            self.db.get_conn()
            .execute("SELECT source_key,remaining_units FROM point_lots ORDER BY id")
            .fetchall()
        )
        with patch.dict(os.environ, {"HANDRAW_ALLOW_ECONOMY_UPGRADE": "YES"}):
            report = upgrade(self.db._dsn, apply=True)
        after = (
            self.db.get_conn()
            .execute("SELECT source_key,remaining_units FROM point_lots ORDER BY id")
            .fetchall()
        )
        self.assertTrue(report["installed"])
        self.assertEqual(before, after)
        self.db.get_conn().execute("UPDATE payment_orders SET status='pending'")
        self.db.get_conn().execute("DELETE FROM schema_migrations WHERE version=119")
        with self.assertRaisesRegex(RuntimeError, "Real payment history"):
            upgrade(self.db._dsn, apply=False)

    def test_unused_principal_refund_after_partial_generation_spend(self):
        from backend.billing_refunds import request_refund, process_refund
        from unittest.mock import patch

        self.paid_order()
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=0")
        q = economy.create_quote(self.db, self.user, [{"ratio": "3:4"}])
        result = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "requestId": "paid-one",
                "prompt": "cat",
                "quoteId": q["quoteId"],
                "confirmCost": True,
            },
        )
        complete_cloud_generation(
            self.db,
            result["genId"],
            "task",
            ["/images/poster-demo-autumn-equinox.webp"],
        )
        refund = request_refund(self.db, self.user, {"orderId": "order-test"})
        self.assertEqual(refund["amountCents"], 975)
        admin = {**self.user, "role": "admin"}
        with (
            patch(
                "backend.billing.load_payment_config",
                return_value={"app_secret": "fixture-secret"},
            ),
            patch(
                "backend.billing._xorpay_api_request", return_value={"status": "ok"}
            ) as provider,
        ):
            process_refund(self.db, admin, {"refundId": refund["refundId"]})
            process_refund(self.db, admin, {"refundId": refund["refundId"]})
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 0, "heldCents": 0},
        )

    def test_earned_points_spent_first_and_unlock_refund_restores_sources(self):
        self.paid_order("points")
        with self.db.transaction() as tx:
            apply_wallet_delta(tx, self.uid, 20, "admin_adjust", "earned")
            apply_wallet_delta(
                tx,
                self.uid,
                -30,
                "unlock_spend",
                "content",
                ref_type="topic",
                ref_id="fixture",
            )
            earned = tx.execute(
                "SELECT remaining_units FROM point_lots WHERE source_kind='earned' AND user_id=?",
                (self.uid,),
            ).fetchone()[0]
            self.assertEqual(earned, 0)
            apply_wallet_delta(
                tx,
                self.uid,
                30,
                "unlock_refund",
                "refund",
                ref_type="topic",
                ref_id="fixture",
            )
        lots = (
            self.db.get_conn()
            .execute(
                "SELECT source_kind,sum(remaining_units) units FROM point_lots WHERE user_id=? GROUP BY source_kind",
                (self.uid,),
            )
            .fetchall()
        )
        self.assertEqual({r[0]: r[1] for r in lots}, {"earned": 20, "purchased": 100})

    def test_closed_bounty_restores_earned_and_purchased_point_sources(self):
        self.paid_order("points")
        with self.db.transaction() as tx:
            apply_wallet_delta(tx, self.uid, 20, "admin_adjust", "contribution")
            apply_wallet_delta(
                tx,
                self.uid,
                -30,
                "bounty_escrow",
                "bounty",
                event_key="bounty-hold",
                ref_type="topic",
                ref_id="bounty-source",
            )
            self.assertEqual(
                tx.execute(
                    "SELECT remaining_units FROM point_lots WHERE user_id=? AND source_kind='purchased'",
                    (self.uid,),
                ).fetchone()[0],
                90,
            )
            apply_wallet_delta(
                tx,
                self.uid,
                30,
                "bounty_admin_refund",
                "bounty closed",
                event_key="bounty-return",
                ref_type="topic",
                ref_id="bounty-source",
            )
            self.assertFalse(
                apply_wallet_delta(
                    tx,
                    self.uid,
                    30,
                    "bounty_admin_refund",
                    "duplicate",
                    event_key="bounty-return",
                    ref_type="topic",
                    ref_id="bounty-source",
                )[1]
            )
        rows = (
            self.db.get_conn()
            .execute(
                "SELECT source_kind,sum(remaining_units) FROM point_lots WHERE user_id=? GROUP BY source_kind",
                (self.uid,),
            )
            .fetchall()
        )
        self.assertEqual({r[0]: r[1] for r in rows}, {"earned": 20, "purchased": 100})
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_reward_caps_and_no_engagement_mint(self):
        from backend.points import reward

        with self.db.transaction() as tx:
            for kind in (
                "welcome",
                "publish_work",
                "invite_inviter",
                "first_collect",
                "first_cheer",
                "honor_upgrade",
            ):
                self.assertFalse(
                    apply_wallet_delta(tx, self.uid, 20, kind, "old reward")[1]
                )
            self.assertEqual(reward(tx, self.uid, "verified", str(self.uid)), 20)
            self.assertEqual(reward(tx, self.uid, "verified", str(self.uid)), 0)
            for index in range(25):
                reward(tx, self.uid, "checkin", f"{self.uid}:day{index}")
            self.assertEqual(
                tx.execute(
                    "SELECT balance FROM wallets WHERE user_id=?", (self.uid,)
                ).fetchone()[0],
                40,
            )

    def test_canvas_reserves_whole_batch_and_dispatch_settles_free_then_cash(self):
        from backend.studio_canvases import save_canvas, preview_canvas, submit_canvas
        from backend.canvas_dispatcher import CanvasDispatcher
        from backend.canvas_runs import get_canvas_run
        from tests.test_studio_canvases import graph
        from unittest.mock import patch

        self.paid_order()
        self.db.get_conn().execute("UPDATE generation_quota_policy SET base_units=1")
        canvas = save_canvas(
            self.db,
            self.user,
            {
                "id": "money_canvas",
                "name": "test",
                "graph": graph(("prompt", ["cat", "dog", "bird"])),
            },
        )
        preview = preview_canvas(self.db, self.user, canvas["id"])
        q = economy.create_quote(
            self.db, self.user, [item["spec"] for item in preview["items"]]
        )
        run = submit_canvas(
            self.db,
            self.user,
            canvas["id"],
            {
                "requestId": "money-batch",
                "planHash": preview["planHash"],
                "quoteId": q["quoteId"],
                "maxAmountCents": q["totalCents"],
            },
        )
        self.assertEqual(economy.cash(self.db.get_conn(), self.uid)["heldCents"], 50)
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["held"], 1)

        def execute(db, user, body, **kwargs):
            result = prepare_cloud_generation(db, user, body)
            complete_cloud_generation(
                db,
                result["genId"],
                "mock-task",
                ["/images/poster-demo-autumn-equinox.webp"],
            )
            return {"ok": True}, 200

        with patch("backend.server.execute_studio_generation", side_effect=execute):
            dispatcher = CanvasDispatcher(self.db)
            for _ in range(3):
                self.assertTrue(dispatcher.dispatch_once())
        result = get_canvas_run(self.db, self.user, run["runId"])["run"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["spentAmountCents"], 50)
        from backend.services import get_studio_workspace

        history = get_studio_workspace(self.db, self.user, collection="history")[
            "history"
        ]
        receipt = next(h["billing"] for h in history if h["runId"] == run["runId"])
        self.assertEqual(
            receipt,
            {
                "amountCents": 50,
                "heldCents": 0,
                "freeUsed": 1,
                "freeHeld": 0,
                "chargeCount": 3,
            },
        )
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 950, "heldCents": 0},
        )

    def test_unlock_royalty_delayed_refund_and_repurchase(self):
        from backend.services import unlock_paid_item
        from backend.admin_services import admin_refund_unlock
        from backend.points import settle_due

        author, _ = register_user(self.db, "resource_author", "FixturePass123!")
        self.paid_order("points")
        self.db.get_conn().execute(
            "INSERT INTO catalog_assets(code,kind,source_type,author_username,author_name,name,unlock_cost,image_url,published_at_ms,created_at,updated_at) VALUES('FA-001','style','community',?,'Author','Test style',30,'/images/styles/S-001.webp',1,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)",
            (author["username"],),
        )
        from backend.resource_discussions import ensure_topic

        with self.db.transaction() as tx:
            resource = dict(
                tx.execute(
                    "SELECT * FROM catalog_assets WHERE code='FA-001'"
                ).fetchone()
            )
            topic_id = ensure_topic(tx, "style", "FA-001", resource)
            # Even a stale/mistaken topic price must not become a second charge.
            tx.execute("UPDATE forum_topics SET price=50 WHERE id=?", (topic_id,))

        def unlock(entry):
            try:
                return unlock_paid_item(self.db, self.user, *entry)
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(2) as pool:
            receipts = list(
                pool.map(unlock, [("asset", "FA-001"), ("topic", topic_id)])
            )
        self.assertEqual(sum(r.get("cost", 0) for r in receipts), 30)
        self.assertEqual(sum(bool(r.get("alreadyUnlocked")) for r in receipts), 1)
        self.assertTrue(
            unlock_paid_item(self.db, self.user, "asset", "fa-001")["alreadyUnlocked"]
        )
        tx = self.db.get_conn()
        earning = tx.execute("SELECT * FROM creator_point_earnings").fetchone()
        self.assertEqual((earning["units"], earning["status"]), (24, "pending"))
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (author["id"],)
            ).fetchone()[0],
            0,
        )
        tx.execute(
            "UPDATE creator_point_earnings SET available_at=now()-interval '1 second'"
        )
        tx.execute("UPDATE wallets SET locked=1 WHERE user_id=?", (author["id"],))
        settle_due(self.db, author["id"])
        self.assertEqual(
            tx.execute(
                "SELECT status FROM creator_point_earnings WHERE id=?", (earning["id"],)
            ).fetchone()[0],
            "pending",
        )
        tx.execute("UPDATE wallets SET locked=0 WHERE user_id=?", (author["id"],))
        settle_due(self.db, author["id"])
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (author["id"],)
            ).fetchone()[0],
            24,
        )
        admin_refund_unlock(
            self.db,
            {**self.user, "role": "admin"},
            earning["unlock_id"],
            "invalid resource",
        )
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (self.uid,)
            ).fetchone()[0],
            100,
        )
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (author["id"],)
            ).fetchone()[0],
            0,
        )
        unlock_paid_item(self.db, self.user, "asset", "FA-001")
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (self.uid,)
            ).fetchone()[0],
            70,
        )
        self.assertEqual(
            tx.execute("SELECT count(*) FROM creator_point_earnings").fetchone()[0], 2
        )

    def test_verification_reward_fires_once_without_opening_wallet(self):
        tx = self.db.get_conn()
        tx.execute(
            "INSERT INTO verified_emails(user_id,email,verified_at) VALUES(?,?,CURRENT_TIMESTAMP::text)",
            (self.uid, "verified@example.test"),
        )
        tx.execute(
            "UPDATE verified_emails SET verified_at=CURRENT_TIMESTAMP::text WHERE user_id=?",
            (self.uid,),
        )
        self.assertEqual(
            tx.execute(
                "SELECT balance FROM wallets WHERE user_id=?", (self.uid,)
            ).fetchone()[0],
            20,
        )
        self.assertEqual(
            tx.execute(
                "SELECT sum(remaining_units) FROM point_lots WHERE user_id=?",
                (self.uid,),
            ).fetchone()[0],
            20,
        )

    def test_cancel_unsubmitted_canvas_releases_only_pending_holds(self):
        from backend.studio_canvases import save_canvas, preview_canvas, submit_canvas
        from tests.test_studio_canvases import graph
        from backend.generation_v3 import cancel_unsubmitted_web_slots

        save_canvas(
            self.db,
            self.user,
            {
                "id": "cancel_canvas",
                "name": "cancel",
                "graph": graph(("prompt", ["a", "b"])),
            },
        )
        preview = preview_canvas(self.db, self.user, "cancel_canvas")
        quote = economy.create_quote(
            self.db, self.user, [item["spec"] for item in preview["items"]]
        )
        submit_canvas(
            self.db,
            self.user,
            "cancel_canvas",
            {
                "requestId": "cancel-batch",
                "planHash": preview["planHash"],
                "quoteId": quote["quoteId"],
                "maxAmountCents": 0,
            },
        )
        cancel_unsubmitted_web_slots(self.db, self.user, "cancel-batch", [0, 1])
        self.assertEqual(economy.quota(self.db.get_conn(), self.uid)["remaining"], 10)

    def test_unknown_refund_is_not_retried(self):
        from backend.billing_refunds import request_refund, process_refund
        from unittest.mock import patch

        self.paid_order()
        refund = request_refund(self.db, self.user, {"orderId": "order-test"})
        admin = {**self.user, "role": "admin"}
        with (
            patch(
                "backend.billing.load_payment_config",
                return_value={"app_secret": "fixture-secret"},
            ),
            patch(
                "backend.billing._xorpay_api_request", side_effect=TimeoutError
            ) as provider,
        ):
            with self.assertRaises(ServiceError):
                process_refund(self.db, admin, {"refundId": refund["refundId"]})
            result = process_refund(self.db, admin, {"refundId": refund["refundId"]})
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(economy.cash(self.db.get_conn(), self.uid)["heldCents"], 1000)
        from backend.billing_refunds import reconcile_refund

        result = reconcile_refund(
            self.db,
            admin,
            {
                "action": "reconcile",
                "refundId": refund["refundId"],
                "outcome": "rejected",
                "providerReference": "merchant-query-123",
                "reason": "merchant verified no refund",
            },
        )
        self.assertFalse(result["resubmitted"])
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 1000, "heldCents": 0},
        )

        self.paid_order(key="order-ambiguous")
        ambiguous = request_refund(self.db, self.user, {"orderId": "order-ambiguous"})
        with (
            patch(
                "backend.billing.load_payment_config",
                return_value={"app_secret": "fixture-secret"},
            ),
            patch(
                "backend.billing._xorpay_api_request",
                return_value={"status": "alipay_api_error"},
            ) as provider,
        ):
            outcome = process_refund(
                self.db, admin, {"refundId": ambiguous["refundId"]}
            )
            process_refund(self.db, admin, {"refundId": ambiguous["refundId"]})
        self.assertEqual(outcome["status"], "unknown")
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(economy.cash(self.db.get_conn(), self.uid)["heldCents"], 1000)
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_refund_callback_wins_while_provider_request_is_in_flight(self):
        from backend.billing_refunds import request_refund, process_refund
        from backend.billing import _refund_order_tx
        from unittest.mock import patch

        self.paid_order()
        req = request_refund(self.db, self.user, {"orderId": "order-test"})

        def callback(*args, **kwargs):
            with self.db.transaction() as tx:
                _refund_order_tx(
                    tx, provider="xorpay", provider_order_id="provider-order-test"
                )
            return {"status": "ok"}

        with (
            patch(
                "backend.billing.load_payment_config",
                return_value={"app_secret": "fixture-secret"},
            ),
            patch(
                "backend.billing._xorpay_api_request", side_effect=callback
            ) as provider,
        ):
            result = process_refund(
                self.db, {**self.user, "role": "admin"}, {"refundId": req["refundId"]}
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 0, "heldCents": 0},
        )
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])

    def test_missing_refund_configuration_keeps_request_pending(self):
        from backend.billing_refunds import request_refund, process_refund
        from unittest.mock import patch

        self.paid_order()
        req = request_refund(self.db, self.user, {"orderId": "order-test"})
        with (
            patch("backend.billing.load_payment_config", return_value={}),
            patch("backend.billing._xorpay_api_request") as provider,
        ):
            with self.assertRaises(ServiceError) as caught:
                process_refund(
                    self.db,
                    {**self.user, "role": "admin"},
                    {"refundId": req["refundId"]},
                )
        self.assertEqual(caught.exception.code, "refund_not_configured")
        provider.assert_not_called()
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT status FROM billing_refund_requests WHERE id=?",
                (req["refundId"],),
            )
            .fetchone()[0],
            "pending",
        )
        self.assertEqual(economy.cash(self.db.get_conn(), self.uid)["heldCents"], 1000)

        from backend.billing_refunds import reconcile_refund

        reconcile_refund(
            self.db,
            {**self.user, "role": "admin"},
            {
                "refundId": req["refundId"],
                "outcome": "completed",
                "providerReference": "merchant-verified-refund-1",
                "reason": "Manually refunded through merchant portal",
            },
        )
        self.assertEqual(
            economy.cash(self.db.get_conn(), self.uid),
            {"balanceCents": 0, "heldCents": 0},
        )
        self.assertTrue(economy.reconcile(self.db.get_conn())["ok"])
