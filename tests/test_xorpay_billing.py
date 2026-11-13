"""Tests for XorPay credit recharge checkout, webhook verification, and order sync (#224)."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend.billing import xorpay_sign
from backend.config import get_public_billing_summary, load_payment_config
from backend.server import HandrawHTTPServer, HandrawRequestHandler
from backend.services import register_user


class XorPayBillingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.cfg_path = self.tmp_path / "payment-service.json"
        self.aid = "708427"
        self.app_secret = "test_xorpay_secret_abcdef123456"
        self.cfg_payload = {
            "provider": "xorpay",
            "aid": self.aid,
            "app_secret": self.app_secret,
            "currency": "CNY",
            "test_mode": False,
            "pay_type": "alipay",
            "packages": [
                {
                    "id": "pack_50",
                    "title": "50 积分尝鲜包",
                    "description": "50 credits",
                    "credits": 50,
                    "price_cents": 500,
                    "price_display": "¥5",
                },
                {
                    "id": "pack_100",
                    "title": "100 积分标准包",
                    "description": "100 credits",
                    "credits": 100,
                    "price_cents": 990,
                    "price_display": "¥9.9",
                    "badge": "推荐",
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

        self.db = open_isolated_postgres(self, seed=True)
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
        body: bytes | dict | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, dict[str, str]]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(headers or {})
        raw: bytes | None = None
        if isinstance(body, dict):
            raw = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        elif isinstance(body, (bytes, bytearray)):
            raw = bytes(body)
        conn.request(method, path, body=raw, headers=hdrs)
        resp = conn.getresponse()
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        resp_bytes = resp.read()
        conn.close()

        ctype = resp_headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                data = json.loads(resp_bytes.decode("utf-8"))
            except Exception:
                data = resp_bytes.decode("utf-8", errors="replace")
        else:
            data = resp_bytes.decode("utf-8", errors="replace")
        return resp.status, data, resp_headers

    def test_xorpay_sign_algorithm(self) -> None:
        # Verify MD5 signature formula
        expected = hashlib.md5("abc123xyz".encode("utf-8")).hexdigest().lower()
        self.assertEqual(xorpay_sign("abc", "123", "xyz"), expected)

    def test_public_plans_never_leak_secrets_and_cny_pricing(self) -> None:
        cfg = load_payment_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["provider"], "xorpay")
        self.assertEqual(cfg["currency"], "CNY")
        pub = get_public_billing_summary(cfg)
        self.assertTrue(pub["enabled"])
        self.assertEqual(pub["provider"], "xorpay")
        self.assertEqual(pub["currency"], "CNY")
        self.assertEqual(len(pub["packages"]), 2)

        st, body, _ = self._req("GET", "/api/billing/plans")
        self.assertEqual(st, 200)
        serialized = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(self.app_secret, serialized)
        self.assertNotIn(self.aid, serialized)

        # Security boundary on demo-only /api/wallet/recharge must remain 503
        st_old, body_old, _ = self._req(
            "POST",
            "/api/wallet/recharge",
            {"amount": 50},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(st_old, 503)
        self.assertEqual(body_old["code"], "payment_disabled")

    def test_checkout_order_creation_and_success(self) -> None:
        captured_requests: list[tuple[str, str, dict[str, Any], str]] = []

        def fake_xorpay_api(method: str, path: str, data=None, *, api_base="https://xorpay.com", timeout=20.0):
            captured_requests.append((method, path, data or {}, api_base))
            return {
                "status": "ok",
                "info": {
                    "aoid": "xorp_order_9988",
                    "order_id": data.get("order_id"),
                    "qr": "https://qr.alipay.com/bax01234test",
                },
            }

        with patch("backend.billing._xorpay_api_request", side_effect=fake_xorpay_api):
            st, res, _ = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_100"},
                {"Origin": "https://studio.handraw-style.com", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st, 200)
        self.assertEqual(res["order"]["packId"], "pack_100")
        self.assertEqual(res["order"]["credits"], 100)
        self.assertEqual(res["order"]["amountCents"], 990)
        self.assertEqual(res["order"]["currency"], "CNY")
        self.assertEqual(res["order"]["status"], "pending")
        self.assertEqual(res["order"]["checkoutId"], "xorp_order_9988")
        self.assertEqual(res["qr"], "https://qr.alipay.com/bax01234test")
        self.assertIn("/api/cashier/708427?", res["checkoutUrl"])

        # Check call to XorPay unified pay endpoint
        method, path, sent_data, _ = captured_requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, f"/api/pay/{self.aid}")
        self.assertEqual(sent_data["price"], "9.90")
        self.assertEqual(sent_data["pay_type"], "alipay")
        order_id = res["order"]["id"]
        self.assertEqual(sent_data["order_id"], order_id)
        expected_sign = xorpay_sign(
            sent_data["name"],
            sent_data["pay_type"],
            sent_data["price"],
            order_id,
            sent_data["notify_url"],
            self.app_secret,
        )
        self.assertEqual(sent_data["sign"], expected_sign)

    def test_checkout_order_fee_error_handling(self) -> None:
        def fake_xorpay_fee_error(method: str, path: str, data=None, *, api_base="https://xorpay.com", timeout=20.0):
            return {"status": "fee_error"}

        with patch("backend.billing._xorpay_api_request", side_effect=fake_xorpay_fee_error):
            st, res, _ = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st, 502)
        self.assertEqual(res["code"], "xorpay_fee_error")
        self.assertIn("手续费", res["error"])

    def test_webhook_signature_verification_and_settlement(self) -> None:
        # First create a pending order
        def fake_pay(method: str, path: str, data=None, *, api_base="https://xorpay.com", timeout=20.0):
            return {
                "status": "ok",
                "info": {"aoid": "aoid_test_1001", "order_id": data.get("order_id"), "qr": "qr_1001"},
            }

        with patch("backend.billing._xorpay_api_request", side_effect=fake_pay):
            st, res, _ = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_100"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st, 200)
        order_id = res["order"]["id"]

        # 1. Invalid signature should be rejected with 401
        invalid_body = urllib.parse.urlencode({
            "aoid": "aoid_test_1001",
            "order_id": order_id,
            "pay_price": "9.90",
            "pay_time": "2026-11-13 14:00:00",
            "sign": "invalid_sig_12345",
        })
        st_bad, body_bad, _ = self._req(
            "POST",
            "/api/webhooks/xorpay",
            invalid_body,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(st_bad, 401)
        self.assertEqual(body_bad["code"], "invalid_webhook_signature")

        # 2. Valid signature should settle order and return HTTP 200 'ok'
        valid_sign = xorpay_sign("aoid_test_1001", order_id, "9.90", "2026-11-13 14:00:00", self.app_secret)
        valid_body = urllib.parse.urlencode({
            "aoid": "aoid_test_1001",
            "order_id": order_id,
            "pay_price": "9.90",
            "pay_time": "2026-11-13 14:00:00",
            "detail": json.dumps({"transaction_id": "ali_202611130001", "buyer": "test_buyer"}),
            "sign": valid_sign,
        })
        st_ok, body_ok, _ = self._req(
            "POST",
            "/api/webhooks/xorpay",
            valid_body,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(st_ok, 200)
        self.assertEqual(body_ok, "ok")

        # Verify wallet credits granted to User A (initial 20 + 100 recharge = 120)
        conn = self.db.get_conn()
        wal = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.user_a["id"],)).fetchone()
        self.assertEqual(wal["balance"], 120)

        # Verify order marked paid in database
        ord_row = conn.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
        self.assertEqual(ord_row["status"], "paid")
        self.assertEqual(ord_row["provider_order_id"], "aoid_test_1001")
        self.assertEqual(ord_row["provider_order_number"], "ali_202611130001")

        # 3. Duplicate webhook should be idempotent (return ok without double crediting)
        st_dup, body_dup, _ = self._req(
            "POST",
            "/api/webhooks/xorpay",
            valid_body,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(st_dup, 200)
        self.assertEqual(body_dup, "ok")
        wal2 = conn.execute("SELECT balance FROM wallets WHERE user_id = ?", (self.user_a["id"],)).fetchone()
        self.assertEqual(wal2["balance"], 120)

    def test_sync_order_from_provider_query2(self) -> None:
        def fake_pay(method: str, path: str, data=None, *, api_base="https://xorpay.com", timeout=20.0):
            return {
                "status": "ok",
                "info": {"aoid": "aoid_test_sync_1", "order_id": data.get("order_id"), "qr": "qr_sync_1"},
            }

        with patch("backend.billing._xorpay_api_request", side_effect=fake_pay):
            st, res, _ = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st, 200)
        order_id = res["order"]["id"]

        # Mock query2 response returning payed
        def fake_query2(method: str, path: str, data=None, *, api_base="https://xorpay.com", timeout=20.0):
            self.assertEqual(method, "GET")
            self.assertIn(f"/api/query2/{self.aid}?", path)
            expected_sign = xorpay_sign(order_id, self.app_secret)
            self.assertIn(f"sign={expected_sign}", path)
            return {
                "status": "payed",
                "aoid": "aoid_test_sync_1",
                "pay_price": "5.00",
                "detail": {"transaction_id": "ali_sync_999"},
            }

        with patch("backend.billing._xorpay_api_request", side_effect=fake_query2):
            st_sync, body_sync, _ = self._req(
                "POST",
                f"/api/billing/orders/{order_id}/sync",
                {},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st_sync, 200)
        self.assertTrue(body_sync["ok"])
        self.assertEqual(body_sync["order"]["status"], "paid")
        self.assertEqual(body_sync["credits"], 70)
        self.assertTrue(body_sync["applied"])

        # Second sync should be idempotent
        with patch("backend.billing._xorpay_api_request", side_effect=fake_query2):
            st_sync2, body_sync2, _ = self._req(
                "POST",
                f"/api/billing/orders/{order_id}/sync",
                {},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st_sync2, 200)
        self.assertFalse(body_sync2["applied"])
        self.assertEqual(body_sync2["credits"], 70)

    def test_user_cross_account_isolation(self) -> None:
        def fake_pay(method: str, path: str, data=None, *, api_base="https://xorpay.com", timeout=20.0):
            return {
                "status": "ok",
                "info": {"aoid": "aoid_iso_1", "order_id": data.get("order_id"), "qr": "qr_iso_1"},
            }

        with patch("backend.billing._xorpay_api_request", side_effect=fake_pay):
            st, res, _ = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
        order_id = res["order"]["id"]

        # Buyer B cannot sync Buyer A's order
        st_bad, body_bad, _ = self._req(
            "POST",
            f"/api/billing/orders/{order_id}/sync",
            {},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(st_bad, 404)
        self.assertEqual(body_bad["code"], "order_not_found")

        # Buyer B's order list does not contain Buyer A's order
        st_list, body_list, _ = self._req(
            "GET",
            "/api/billing/orders",
            headers={"Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(st_list, 200)
        self.assertEqual(len(body_list["orders"]), 0)


if __name__ == "__main__":
    unittest.main()
