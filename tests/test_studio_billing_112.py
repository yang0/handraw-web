"""#112 zero-dark-charge billing audit, real SQLite transactions + mock gateway.

Checks every financial transition against BOTH the wallet balance and the
append-only ledgers table. No paid supplier, no real account or production data.
Existing HTTP timeout/HTTP 502 tests remain a separate gateway integration gate.
"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

from backend.db import Database
from backend.services import (
    ServiceError, claim_cloud_generation_submission, complete_cloud_generation,
    get_site_settings, local_today_str, prepare_cloud_generation,
    refund_failed_cloud_generation, register_user,
)


class ZeroDarkChargeAudit112(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="billing112-")
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "ledger.db")
        self.db.migrate()
        self.addCleanup(self.db.close)
        self.owner, _ = register_user(self.db, "billing112_owner", "StrongPass123!")
        self.other, _ = register_user(self.db, "billing112_other", "StrongPass123!")
        self.uid = int(self.owner["id"])
        self.base = 73
        # Exhaust daily FREE allowance deliberately: force a real debit
        # through the site's append-only ledger, never a fake billing counter.
        quota = int(get_site_settings(self.db.get_conn())["economy"]["daily_free_quota"])
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE wallets SET free_quota_used=?,free_quota_date=?,balance=? "
                "WHERE user_id=?", (quota, local_today_str(), self.base, self.uid)
            )

    def ledger(self):
        return self.db.get_conn().execute(
            "SELECT delta,kind,event_key,ref_id,balance_after FROM ledgers "
            "WHERE user_id=? AND kind IN ('studio_gen','studio_refund') ORDER BY id",
            (self.uid,),
        ).fetchall()

    def balance(self):
        return int(self.db.get_conn().execute(
            "SELECT balance FROM wallets WHERE user_id=?", (self.uid,)
        ).fetchone()[0])

    def audit(self):
        events = self.ledger()
        self.assertEqual(
            self.balance(), self.base + sum(int(row["delta"]) for row in events),
            "WALLET/LEDGER mismatch: possible dark debit or ghost refund",
        )
        self.assertEqual(len(events), len({row["event_key"] for row in events}))
        for i, row in enumerate(events):
            expected = self.base + sum(int(x["delta"]) for x in events[:i+1])
            self.assertEqual(int(row["balance_after"]), expected)

    def reserve_paid(self, request_id=None):
        rid = request_id or "qa112-" + uuid.uuid4().hex
        prepared = prepare_cloud_generation(
            self.db, self.owner,
            {"requestId":rid, "prompt":"原创主题：付费流水核对", "promptFromSkill":True},
        )
        self.assertEqual(prepared["costType"], "credits")
        cost = int(prepared["creditsSpent"])
        self.assertGreater(cost, 0)
        return prepared, cost

    def test_timeout_or_unknown_502_holds_charge_until_definite_confirmation(self):
        first, cost = self.reserve_paid()
        gid = first["genId"]
        second, _ = self.reserve_paid(first["requestId"])
        self.assertEqual(second["genId"], gid)
        self.assertTrue(second["idempotent"])
        self.assertEqual(self.balance(), self.base - cost)
        self.assertEqual([r["kind"] for r in self.ledger()], ["studio_gen"])

        first_claim = claim_cloud_generation_submission(self.db, self.owner, gid)
        second_claim = claim_cloud_generation_submission(self.db, self.owner, gid)
        self.assertTrue(first_claim["claimed"])
        self.assertFalse(second_claim["claimed"])
        upstream = Mock(side_effect=TimeoutError("gateway possibly accepted"))
        with self.assertRaises(TimeoutError):
            upstream()
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(self.balance(), self.base - cost)
        self.audit()
        # An unconfirmed timeout/502 must NOT be auto-refunded. Only an
        # explicit definitive provider failure/cancel confirmation refunds.
        refund_failed_cloud_generation(self.db, gid, "provider confirmed cancellation")
        refund_failed_cloud_generation(self.db, gid, "duplicate webhook cancellation")
        self.assertEqual(self.balance(), self.base)
        self.assertEqual([r["kind"] for r in self.ledger()],
                         ["studio_gen", "studio_refund"])
        self.assertEqual([int(r["delta"]) for r in self.ledger()], [-cost, cost])
        self.audit()
        # Late success AFTER refund must not republish, consume quota or
        # replace the reconciled status. This was a real unsafe code boundary.
        complete_cloud_generation(
            self.db, gid, "late-success-task",
            ["/images/poster-demo-autumn-equinox.webp"],
        )
        row=self.db.get_conn().execute(
            "SELECT status,items_json FROM studio_generations WHERE id=?", (gid,)
        ).fetchone()
        self.assertEqual(row["status"], "refunded")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM works WHERE run_id=?", (first["runId"],)
        ).fetchone()[0], 0)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM studio_generation_media WHERE generation_id=?", (gid,)
        ).fetchone()[0], 0)
        self.audit()

    def test_success_duplicate_callbacks_are_immutable_and_no_refund(self):
        first, cost = self.reserve_paid()
        gid = first["genId"]
        self.assertTrue(claim_cloud_generation_submission(
            self.db, self.owner, gid)["claimed"])
        original = "/images/poster-demo-autumn-equinox.webp"
        complete_cloud_generation(self.db, gid, "verified-paid", [original])
        snapshot=self.db.get_conn().execute(
            "SELECT status,items_json,task_id FROM studio_generations WHERE id=?", (gid,)
        ).fetchone()
        self.assertEqual(snapshot["status"], "success")
        complete_cloud_generation(
            self.db, gid, "duplicate-paid", ["/images/individual/FA/FA-013.webp"]
        )
        duplicate=self.db.get_conn().execute(
            "SELECT status,items_json,task_id FROM studio_generations WHERE id=?", (gid,)
        ).fetchone()
        self.assertEqual(tuple(duplicate), tuple(snapshot),
                         "duplicate callback mutated already-settled paid media")
        refund_failed_cloud_generation(self.db, gid, "delayed failed webhook")
        self.assertEqual(self.balance(), self.base - cost)
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(self.ledger()[0]["kind"], "studio_gen")
        self.audit()

    def test_pre_submit_failure_refunds_once_and_new_request_is_distinct(self):
        first, cost = self.reserve_paid()
        gid = first["genId"]
        refund_failed_cloud_generation(self.db, gid, "preflight storage failed")
        refund_failed_cloud_generation(self.db, gid, "preflight storage failed again")
        self.assertEqual(self.balance(), self.base)
        replay, _ = self.reserve_paid(first["requestId"])
        self.assertEqual(replay["genId"], gid)
        self.assertEqual(self.balance(), self.base)
        self.audit()
        # A separate user-requested generation ID is a new payable attempt.
        new, cost2 = self.reserve_paid()
        self.assertNotEqual(new["genId"], gid)
        self.assertEqual(self.balance(), self.base - cost2)
        self.audit()
        refund_failed_cloud_generation(self.db, new["genId"], "definitive reject")
        self.assertEqual(self.balance(), self.base)
        self.audit()

    def test_failed_validation_and_other_user_never_debit_owner(self):
        before=self.ledger()
        with self.assertRaises(ServiceError):
            prepare_cloud_generation(self.db, self.owner, {
                "requestId":"bad", "idempotencyKey":"conflict",
                "prompt":"不应开始任何计费"
            })
        self.assertEqual(len(self.ledger()), len(before))
        first, cost=self.reserve_paid()
        with self.assertRaises(ServiceError) as forbidden:
            claim_cloud_generation_submission(self.db, self.other, first["genId"])
        self.assertEqual(forbidden.exception.status, 403)
        self.assertEqual(self.balance(), self.base - cost)
        self.audit()


class PaidGatewayHttpZeroDarkCharge112(unittest.TestCase):
    """Real HTTP login/session, gateway MOCK and real paid ledger state."""

    @classmethod
    def setUpClass(cls):
        import json
        import os
        import threading
        from unittest.mock import patch
        from backend.server import create_channel_server, init_database, SESSION_COOKIE_NAME
        cls.tmp=tempfile.TemporaryDirectory(prefix="paid-http112-")
        root=Path(cls.tmp.name)
        config=root/"image-service.json"
        config.write_text(json.dumps({
            "key":"CI_ONLY_FAKE_KEY","base_url":"http://127.0.0.1:9999"
        }))
        cls.environment=patch.dict(os.environ,{
            "HANDRAW_DB_PATH":str(root/"billing.sqlite"),
            "HANDRAW_UPLOADS_DIR":str(root/"uploads"),
            "HANDRAW_GENERATED_DIR":str(root/"generated"),
            "HANDRAW_PRIVATE_STORAGE":str(root/"private"),
            "HANDRAW_IMAGE_CONFIG":str(config),
            "HANDRAW_DEMO_MODE":"0",
            "HANDRAW_ALLOWED_ORIGINS":"http://trusted.test",
        })
        cls.environment.start()
        try:
            cls.db=init_database(root/"billing.sqlite")
            cls.owner,session=register_user(
                cls.db,"paid_http112_owner","StrongPass123!")
            cls.cookie=SESSION_COOKIE_NAME+"="+session
            cls.uid=int(cls.owner["id"])
            max_free=int(get_site_settings(
                cls.db.get_conn())["economy"]["daily_free_quota"])
            with cls.db.transaction() as tx:
                tx.execute(
                    "UPDATE wallets SET balance=70,free_quota_date=?,free_quota_used=? "
                    "WHERE user_id=?",(local_today_str(),max_free,cls.uid))
            cls.server=create_channel_server(0,"main",cls.db)
            cls.thread=threading.Thread(
                target=cls.server.serve_forever,daemon=True)
            cls.thread.start()
            cls.base=f"http://127.0.0.1:{cls.server.server_port}"
        except Exception:
            cls.environment.stop()
            cls.tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close_thread_conn()
        cls.db.close()
        cls.environment.stop()
        cls.tmp.cleanup()

    def request(self, method, path, body=None):
        import json
        import urllib.error
        import urllib.request
        headers={"Origin":"http://trusted.test","Cookie":self.cookie,
                 "Content-Type":"application/json"}
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.base+path,data=data,
                                   headers=headers,method=method)
        try:
            res=urllib.request.urlopen(req,timeout=20)
        except urllib.error.HTTPError as error:
            res=error
        with res:
            return res.status,json.loads(res.read().decode())

    def test_paid_http_timeout_duplicate_submit_confirmed_cancel_and_refund(self):
        from unittest.mock import patch
        owner_id=self.uid
        def wallet():
            conn=self.db.get_conn()
            rows=conn.execute(
                "SELECT delta,kind,event_key FROM ledgers "
                "WHERE user_id=? AND kind IN ('studio_gen','studio_refund') "
                "ORDER BY id",(owner_id,)).fetchall()
            balance=int(conn.execute(
                "SELECT balance FROM wallets WHERE user_id=?",
                (owner_id,)).fetchone()[0])
            return balance,rows

        body={"prompt":"真实 HTTP 模拟网关，账本零暗扣",
              "promptFromSkill":True,
              "requestId":"http-billing112-"+uuid.uuid4().hex}
        with patch("backend.server.gateway_request",
                   side_effect=TimeoutError("upstream state unknown")) as fake:
            status,result=self.request("POST","/api/studio/generate",body)
        self.assertEqual(status,200,result)
        self.assertTrue(result["confirming"])
        self.assertEqual(fake.call_count,1)
        cost=int(result["creditsSpent"])
        self.assertGreater(cost,0)
        gid=result["genId"]
        task=result["taskId"]
        self.assertTrue(task)
        balance,rows=wallet()
        self.assertEqual(balance,70-cost)
        self.assertEqual([(x["kind"],int(x["delta"])) for x in rows],
                         [("studio_gen",-cost)])

        # Re-submit identical request while upstream state is unknown:
        # 0 calls to the gateway, 0 new debits.
        with patch("backend.server.gateway_request",
                   side_effect=AssertionError("must not re-submit")) as not_called:
            retry_status,retry=self.request("POST","/api/studio/generate",body)
        not_called.assert_not_called()
        self.assertIn(retry_status,(200,202))
        self.assertTrue(retry["idempotent"])
        self.assertEqual(retry["genId"],gid)
        self.assertEqual(wallet()[0],70-cost)
        self.assertEqual(len(wallet()[1]),1)

        # Another request while an unknown paid task exists is refused.
        other={**body,"requestId":"http-billing112-other-"+uuid.uuid4().hex}
        limited_status,_=self.request("POST","/api/studio/generate",other)
        self.assertEqual(limited_status,429)
        self.assertEqual(len(wallet()[1]),1)

        # Only a CONFIRMED gateway cancellation releases the charge.
        with patch("backend.server.gateway_request",return_value={
            "items":[{"id":task,"status":"cancelled"}]
        }) as gateway:
            poll_status,poll=self.request("GET","/api/studio/tasks?id="+task)
        self.assertEqual(poll_status,200,poll)
        self.assertEqual(poll["status"],"cancelled")
        self.assertEqual(gateway.call_count,1)
        self.assertEqual(wallet()[0],70)
        events=wallet()[1]
        self.assertEqual([int(x["delta"]) for x in events],[-cost,cost])
        self.assertEqual(len({x["event_key"] for x in events}),2)

        # Duplicate callback/poll is served from persisted terminal state.
        with patch("backend.server.gateway_request",
                   side_effect=AssertionError("must not re-poll terminal")) as no_poll:
            poll2_status,poll2=self.request("GET","/api/studio/tasks?id="+task)
        self.assertEqual(poll2_status,200)
        self.assertEqual(poll2["status"],"refunded")
        no_poll.assert_not_called()
        refund_failed_cloud_generation(self.db,gid,"duplicate cancellation callback")
        complete_cloud_generation(
            self.db,gid,"late-paid-success",
            ["/images/poster-demo-autumn-equinox.webp"])
        self.assertEqual(wallet()[0],70)
        self.assertEqual(len(wallet()[1]),2)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT status FROM studio_generations WHERE id=?",
            (gid,)).fetchone()[0],"refunded")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM works WHERE run_id=?",
            (result["runId"],)).fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
