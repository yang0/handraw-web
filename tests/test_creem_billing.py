"""Tests for Creem credit recharge checkout, webhook verification, and order sync (#193)."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import get_public_billing_summary, load_payment_config
from tests.legacy_database import init_legacy_database
from backend.server import HandrawHTTPServer, HandrawRequestHandler
from backend.services import register_user


class CreemBillingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "billing_test.db"
        self.cfg_path = self.tmp_path / "payment-service.json"
        self.webhook_secret = "whsec_test_9d3c7a1f44b2c88e5011"
        self.api_key = "creem_test_api_key_placeholder"
        self.cfg_payload = {
            "provider": "creem",
            "test_mode": True,
            "currency": "USD",
            "api_key": self.api_key,
            "webhook_secret": self.webhook_secret,
            "packages": [
                {
                    "id": "pack_50",
                    "title": "50 积分尝鲜包",
                    "description": "50 credits",
                    "credits": 50,
                    "price_cents": 100,
                    "price_display": "$1",
                    "product_id": "prod_test_50_pack",
                },
                {
                    "id": "pack_100",
                    "title": "100 积分标准包",
                    "description": "100 credits",
                    "credits": 100,
                    "price_cents": 199,
                    "price_display": "$1.99",
                    "badge": "推荐",
                    "product_id": "prod_test_100_pack",
                },
            ],
        }
        self.cfg_path.write_text(json.dumps(self.cfg_payload, ensure_ascii=False), encoding="utf-8")

        self.env_patch = patch.dict(
            os.environ,
            {
                "HANDRAW_PAYMENT_CONFIG": str(self.cfg_path),
                "HANDRAW_DEMO_MODE": "0",
                "HANDRAW_ENABLE_RECHARGE": "0",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test,https://handraw-style.com,https://studio.handraw-style.com",
            },
        )
        self.env_patch.start()

        self.db = init_legacy_database(self.db_path)
        self.user_a, self.tok_a = register_user(self.db, "buyer_a", "Pass123456!", "buyera@example.test", "买家A")
        self.user_b, self.tok_b = register_user(self.db, "buyer_b", "Pass123456!", "buyerb@example.test", "买家B")

        self.httpd = HandrawHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"
        self.httpd.db = self.db
        self.httpd.allow_demo_routes = False
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env_patch.stop()
        self.tmp.cleanup()

    def _req(
        self,
        method: str,
        path: str,
        body: bytes | dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(headers or {})
        raw: bytes | None = None
        if isinstance(body, dict):
            raw = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(body, (bytes, bytearray)):
            raw = bytes(body)
        conn.request(method, path, body=raw, headers=hdrs)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status, data

    def _sign_webhook(self, raw_body: bytes) -> str:
        return hmac.new(self.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    def _sign_redirect(self, pairs: list[tuple[str, str]]) -> str:
        parts = [f"{k}={v}" for k, v in pairs if v not in ("", "null")]
        parts.append(f"salt={self.api_key}")
        sig = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        from urllib.parse import urlencode
        return urlencode([*pairs, ("signature", sig)])

    def test_public_plans_never_leak_secrets_and_legacy_recharge_stays_disabled(self) -> None:
        cfg = load_payment_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["provider"], "creem")
        self.assertEqual(cfg["currency"], "USD")
        pub = get_public_billing_summary(cfg)
        self.assertTrue(pub["enabled"])
        self.assertEqual(pub["provider"], "creem")
        self.assertEqual(len(pub["packages"]), 2)

        st, body = self._req("GET", "/api/billing/plans")
        self.assertEqual(st, 200)
        serialized = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(self.api_key, serialized)
        self.assertNotIn(self.webhook_secret, serialized)
        self.assertNotIn("prod_test_50_pack", serialized)
        self.assertNotIn("prod_test_100_pack", serialized)

        # Security boundary on demo-only /api/wallet/recharge must remain 503
        st_old, body_old = self._req(
            "POST",
            "/api/wallet/recharge",
            {"amount": 50},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(st_old, 503)
        self.assertEqual(body_old["code"], "payment_disabled")

    def test_checkout_webhook_settle_idempotent_and_refund(self) -> None:
        captured_requests: list[tuple[str, str, dict, bool]] = []

        def fake_creem_api(method: str, path: str, api_key: str, payload=None, *, test_mode=True, timeout=20.0):
            captured_requests.append((method, path, payload or {}, test_mode))
            self.assertEqual(api_key, self.api_key)
            return {
                "id": "ch_creem_1234",
                "object": "checkout",
                "status": "pending",
                "mode": "test",
                "checkout_url": "https://checkout.creem.io/test/payment/ch_creem_1234",
            }

        with patch("backend.billing._creem_api_request", side_effect=fake_creem_api):
            st, res = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_100"},
                {"Origin": "https://studio.handraw-style.com", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st, 200)
        self.assertEqual(res["order"]["packId"], "pack_100")
        self.assertEqual(res["order"]["credits"], 100)
        self.assertEqual(res["order"]["amountCents"], 199)
        self.assertEqual(res["order"]["currency"], "USD")
        self.assertEqual(res["order"]["status"], "pending")
        self.assertEqual(res["order"]["checkoutId"], "ch_creem_1234")
        self.assertEqual(res["checkoutUrl"], "https://checkout.creem.io/test/payment/ch_creem_1234")

        method, path, sent_payload, sent_test_mode = captured_requests[0]
        self.assertEqual((method, path, sent_test_mode), ("POST", "/v1/checkouts", True))
        self.assertEqual(sent_payload["product_id"], "prod_test_100_pack")
        order_id = res["order"]["id"]
        self.assertEqual(sent_payload["request_id"], order_id)
        self.assertEqual(sent_payload["success_url"], f"https://handraw-style.com/?view=wallet&order={order_id}")

        # Numeric loopback origin 127.0.0.1 is normalized to localhost for Creem URL validation
        from backend.billing import _creem_compatible_origin
        self.assertEqual(_creem_compatible_origin("http://127.0.0.1:3080"), "http://localhost:3080")

        custom_uid = str(self.user_a["id"])
        hook_payload = {
            "id": "evt_creem_1",
            "eventType": "checkout.completed",
            "created_at": 1730000000000,
            "object": {
                "id": "ch_creem_1234",
                "object": "checkout",
                "request_id": order_id,
                "status": "completed",
                "mode": "test",
                "product": {"id": "prod_test_100_pack", "currency": "USD", "price": 199},
                "order": {
                    "id": "ord_creem_9988",
                    "object": "order",
                    "product": "prod_test_100_pack",
                    "amount": 199,
                    "amount_paid": 199,
                    "currency": "USD",
                    "status": "paid",
                    "transaction": "tran_creem_5566",
                    "mode": "test",
                },
                "metadata": {"order_id": order_id, "user_id": custom_uid, "pack_id": "pack_100"},
            },
        }
        raw_hook = json.dumps(hook_payload).encode("utf-8")

        # Bad signature must be rejected 401
        st_bad, bad_res = self._req(
            "POST",
            "/api/webhooks/creem",
            raw_hook,
            {"creem-signature": "deadbeef"},
        )
        self.assertEqual(st_bad, 401)
        self.assertEqual(bad_res["code"], "invalid_webhook_signature")

        # Valid server-to-server webhook settles +100 credits
        sig = self._sign_webhook(raw_hook)
        st_ok, ok_res = self._req(
            "POST",
            "/api/webhooks/creem",
            raw_hook,
            {"creem-signature": sig},
        )
        self.assertEqual(st_ok, 200)
        self.assertTrue(ok_res["applied"])
        self.assertEqual(ok_res["order"]["status"], "paid")
        self.assertEqual(ok_res["credits"], 120)

        # Duplicate delivery stays idempotent
        st_dup, dup_res = self._req(
            "POST",
            "/api/webhooks/creem",
            raw_hook,
            {"creem-signature": sig},
        )
        self.assertEqual(st_dup, 200)
        self.assertTrue(dup_res["duplicate"])

        # Buyer A sees paid order; Buyer B sees empty
        st_list_a, list_a = self._req("GET", "/api/billing/orders", headers={"Authorization": f"Bearer {self.tok_a}"})
        st_list_b, list_b = self._req("GET", "/api/billing/orders", headers={"Authorization": f"Bearer {self.tok_b}"})
        self.assertEqual(st_list_a, 200)
        self.assertEqual(len(list_a["orders"]), 1)
        self.assertEqual(list_a["orders"][0]["status"], "paid")
        self.assertEqual(st_list_b, 200)
        self.assertEqual(list_b["orders"], [])

        # Refund webhook reverses credits
        refund_payload = {
            "id": "evt_creem_2",
            "eventType": "refund.created",
            "created_at": 1730000010000,
            "object": {
                "id": "ref_creem_1",
                "object": "refund",
                "status": "succeeded",
                "refund_amount": 199,
                "refund_currency": "USD",
                "reason": "requested_by_customer",
                "mode": "test",
                "transaction": {"id": "tran_creem_5566", "order": "ord_creem_9988", "status": "refunded"},
                "checkout": {
                    "id": "ch_creem_1234",
                    "request_id": order_id,
                    "product": "prod_test_100_pack",
                    "metadata": {"order_id": order_id, "user_id": custom_uid},
                },
                "order": {"id": "ord_creem_9988", "status": "paid", "mode": "test"},
            },
        }
        raw_refund = json.dumps(refund_payload).encode("utf-8")
        st_ref, ref_res = self._req(
            "POST",
            "/api/webhooks/creem",
            raw_refund,
            {"creem-signature": self._sign_webhook(raw_refund)},
        )
        self.assertEqual(st_ref, 200)
        self.assertTrue(ref_res["applied"])
        self.assertEqual(ref_res["order"]["status"], "refunded")
        self.assertEqual(ref_res["credits"], 20)

    def test_checkout_gateway_failure_marks_order_failed(self) -> None:
        from backend.services import ServiceError

        with patch(
            "backend.billing._creem_api_request",
            side_effect=ServiceError("gw down", status=502, code="payment_gateway_error"),
        ):
            st, _ = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st, 502)
        _, orders_res = self._req("GET", "/api/billing/orders", headers={"Authorization": f"Bearer {self.tok_a}"})
        self.assertEqual(orders_res["orders"][0]["status"], "failed")

    def test_sync_verifies_redirect_signature_ownership_and_prevents_hijack(self) -> None:
        with patch("backend.billing._creem_api_request") as mock_api:
            mock_api.return_value = {
                "id": "ch_a",
                "status": "pending",
                "mode": "test",
                "checkout_url": "https://checkout.creem.io/test/ch_a",
            }
            _, chk_a = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
            mock_api.return_value = {
                "id": "ch_b",
                "status": "pending",
                "mode": "test",
                "checkout_url": "https://checkout.creem.io/test/ch_b",
            }
            _, chk_b = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
            )

        ord_a = chk_a["order"]["id"]
        ord_b = chk_b["order"]["id"]

        # Buyer B cannot sync Buyer A's order
        st_idor, _ = self._req(
            "POST",
            f"/api/billing/orders/{ord_a}/sync",
            {"checkoutId": "ch_a"},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(st_idor, 404)

        # Checkout ID mismatch rejected 403
        st_chk_mismatch, bad_chk = self._req(
            "POST",
            f"/api/billing/orders/{ord_b}/sync",
            {"checkoutId": "ch_a"},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(st_chk_mismatch, 403)
        self.assertEqual(bad_chk["code"], "checkout_id_mismatch")

        # Tampered redirect signature rejected 403
        st_bad_sig, bad_sig = self._req(
            "POST",
            f"/api/billing/orders/{ord_a}/sync",
            {"redirectQuery": f"view=wallet&order={ord_a}&checkout_id=ch_a&order_id=ord_creem_777&signature=0000"},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(st_bad_sig, 403)
        self.assertEqual(bad_sig["code"], "redirect_signature_mismatch")

        signed_qs = self._sign_redirect(
            [
                ("checkout_id", "ch_a"),
                ("order_id", "ord_creem_777"),
                ("customer_id", "cust_creem_1"),
                ("product_id", "prod_test_50_pack"),
                ("request_id", ord_a),
            ]
        )

        # Underpaid/mismatched product from upstream rejected 400
        with patch("backend.billing._creem_api_request") as mock_api:
            mock_api.return_value = {
                "id": "ch_a",
                "status": "completed",
                "mode": "test",
                "request_id": ord_a,
                "product": "prod_test_50_pack",
                "order": {
                    "id": "ord_creem_777",
                    "status": "paid",
                    "currency": "USD",
                    "amount": 50,
                    "amount_paid": 50,
                    "product": "prod_test_50_pack",
                },
            }
            st_underpaid, underpaid = self._req(
                "POST",
                f"/api/billing/orders/{ord_a}/sync",
                {"redirectQuery": f"view=wallet&order={ord_a}&{signed_qs}"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
            self.assertEqual(st_underpaid, 400)
            self.assertEqual(underpaid["code"], "amount_mismatch")

            # Authentic completed checkout settles +50 credits even when clicked without redirectQuery
            mock_api.return_value = {
                "id": "ch_a",
                "status": "completed",
                "mode": "test",
                "request_id": ord_a,
                "product": "prod_test_50_pack",
                "order": {
                    "id": "ord_creem_777",
                    "status": "paid",
                    "currency": "USD",
                    "amount": 100,
                    "amount_paid": 100,
                    "transaction": "tran_creem_777",
                    "product": "prod_test_50_pack",
                },
            }
            st_sync, sync_res = self._req(
                "POST",
                f"/api/billing/orders/{ord_a}/sync",
                {"redirectQuery": f"view=wallet&order={ord_a}&{signed_qs}"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
            self.assertEqual(st_sync, 200)
            self.assertTrue(sync_res["applied"])
            self.assertEqual(sync_res["credits"], 70)
            self.assertEqual(sync_res["order"]["status"], "paid")

            # Duplicate claim of ord_creem_777 against ord_b fails 409
            mock_api.return_value = {
                "id": "ch_b",
                "status": "completed",
                "mode": "test",
                "request_id": ord_b,
                "product": "prod_test_50_pack",
                "order": {
                    "id": "ord_creem_777",
                    "status": "paid",
                    "currency": "USD",
                    "amount": 100,
                    "amount_paid": 100,
                    "product": "prod_test_50_pack",
                },
            }
            st_dup_claim, dup_claim = self._req(
                "POST",
                f"/api/billing/orders/{ord_b}/sync",
                {},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
            )
            self.assertEqual(st_dup_claim, 409)
            self.assertEqual(dup_claim["code"], "provider_order_conflict")

    def test_rejects_test_mode_webhook_when_configured_live_and_routes_base_url(self) -> None:
        from backend.billing import CREEM_LIVE_API_BASE, CREEM_TEST_API_BASE, _creem_api_base

        self.assertEqual(_creem_api_base("creem_live_abc", False), CREEM_LIVE_API_BASE)
        self.assertEqual(_creem_api_base("creem_live_abc", True), CREEM_TEST_API_BASE)
        self.assertEqual(_creem_api_base("creem_test_abc", False), CREEM_TEST_API_BASE)

        self.cfg_payload["api_key"] = "creem_live_key_for_guard_test"
        self.cfg_payload["test_mode"] = False
        self.cfg_path.write_text(json.dumps(self.cfg_payload, ensure_ascii=False), encoding="utf-8")

        hook_payload = {
            "id": "evt_live_guard",
            "eventType": "checkout.completed",
            "object": {
                "id": "ch_test_in_live",
                "status": "completed",
                "mode": "test",
                "order": {"id": "ord_test_in_live", "status": "paid", "mode": "test"},
            },
        }
        raw = json.dumps(hook_payload).encode("utf-8")
        st, body = self._req(
            "POST",
            "/api/webhooks/creem",
            raw,
            {"creem-signature": self._sign_webhook(raw)},
        )
        self.assertEqual(st, 400)
        self.assertEqual(body["code"], "test_mode_mismatch")

    def test_creem_api_request_retries_once_on_transient_transport_error(self) -> None:
        import urllib.error
        from backend.billing import _creem_api_request

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"id": "ch_ok", "checkout_url": "https://checkout.creem.io/test/ch_ok"}).encode("utf-8")

        attempts = {"count": 0}
        seen_headers: list[dict[str, str]] = []

        def flaky_open(req, timeout=20.0):
            attempts["count"] += 1
            seen_headers.append(dict(req.header_items()))
            if attempts["count"] == 1:
                raise urllib.error.URLError("SSL: UNEXPECTED_EOF_WHILE_READING")
            return _FakeResp()

        with patch("backend.billing.open_url", side_effect=flaky_open):
            res = _creem_api_request("POST", "/v1/checkouts", self.api_key, {"product_id": "prod_test_50_pack"}, test_mode=True)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(res["id"], "ch_ok")
        self.assertEqual(seen_headers[0].get("X-api-key"), self.api_key)


if __name__ == "__main__":
    unittest.main()
