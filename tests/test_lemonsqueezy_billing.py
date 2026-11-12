"""Tests for Lemon Squeezy credit recharge checkout, webhook, and order sync (#185)."""
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
from backend.server import HandrawHTTPServer, HandrawRequestHandler, init_database
from backend.services import register_user


class LemonSqueezyBillingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "billing_test.db"
        self.cfg_path = self.tmp_path / "payment-service.json"
        self.webhook_secret = "test_whsec_9d3c7a1f44b2c88e5011"
        self.api_key = "test_ls_api_jwt_placeholder"
        self.cfg_payload = {
            "provider": "lemonsqueezy",
            "store_id": "521462",
            "test_mode": True,
            "currency": "CNY",
            "api_key": self.api_key,
            "webhook_secret": self.webhook_secret,
            "packages": [
                {
                    "id": "pack_50",
                    "title": "50 积分加油包",
                    "description": "50 credits",
                    "credits": 50,
                    "price_cents": 500,
                    "price_display": "¥5",
                    "variant_id": "100001",
                },
                {
                    "id": "pack_100",
                    "title": "100 积分加油包",
                    "description": "100 credits",
                    "credits": 100,
                    "price_cents": 990,
                    "price_display": "¥9.9",
                    "badge": "热销",
                    "variant_id": "100002",
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

        self.db = init_database(self.db_path)
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

    def test_public_plans_never_leak_secrets_and_legacy_recharge_stays_disabled(self) -> None:
        cfg = load_payment_config()
        self.assertTrue(cfg["enabled"])
        pub = get_public_billing_summary(cfg)
        self.assertTrue(pub["enabled"])
        self.assertEqual(len(pub["packages"]), 2)

        st, body = self._req("GET", "/api/billing/plans")
        self.assertEqual(st, 200)
        serialized = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(self.api_key, serialized)
        self.assertNotIn(self.webhook_secret, serialized)
        self.assertNotIn("100001", serialized)

        # Existing security boundary on demo-only /api/wallet/recharge must remain 503
        st_old, body_old = self._req(
            "POST",
            "/api/wallet/recharge",
            {"amount": 50},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(st_old, 503)
        self.assertEqual(body_old["code"], "payment_disabled")

    def test_checkout_webhook_settle_idempotent_and_refund(self) -> None:
        captured_requests: list[tuple[str, str, dict]] = []

        def fake_lemon_api(method: str, path: str, api_key: str, payload=None, *, timeout=20.0):
            captured_requests.append((method, path, payload or {}))
            self.assertEqual(api_key, self.api_key)
            return {
                "data": {
                    "id": "chk_uuid_1234",
                    "attributes": {"url": "https://handraw.lemonsqueezy.com/checkout/chk_uuid_1234"},
                }
            }

        with patch("backend.billing._lemon_api_request", side_effect=fake_lemon_api):
            st, res = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_100"},
                {"Origin": "https://studio.handraw-style.com", "Authorization": f"Bearer {self.tok_a}"},
            )
        self.assertEqual(st, 200)
        self.assertEqual(res["order"]["packId"], "pack_100")
        self.assertEqual(res["order"]["credits"], 100)
        self.assertEqual(res["order"]["status"], "pending")
        self.assertIn("https://handraw.lemonsqueezy.com/checkout/", res["checkoutUrl"])

        # Confirm redirect_url normalized back to trusted main portal origin (no open redirect / subdomain leakage)
        _, _, sent_payload = captured_requests[0]
        redir = sent_payload["data"]["attributes"]["product_options"]["redirect_url"]
        self.assertTrue(redir.startswith("https://handraw-style.com/?view=wallet&order="))
        self.assertIn("ls_order=[order_id]", redir)
        self.assertIn("ls_ident=[order_identifier]", redir)

        order_id = res["order"]["id"]
        custom_uid = str(self.user_a["id"])

        # Bad signature must be rejected 401
        hook_payload = {
            "meta": {
                "event_name": "order_created",
                "webhook_id": "wh_evt_1",
                "custom_data": {"order_id": order_id, "user_id": custom_uid, "pack_id": "pack_100"},
            },
            "data": {
                "type": "orders",
                "id": "998877",
                "attributes": {
                    "store_id": 521462,
                    "identifier": "ls-uuid-998877",
                    "order_number": 5201,
                    "status": "paid",
                    "refunded": False,
                    "test_mode": True,
                    "currency": "USD",
                    "total": 140,
                    "first_order_item": {"variant_id": 100002},
                },
            },
        }
        raw_hook = json.dumps(hook_payload).encode("utf-8")
        st_bad, bad_res = self._req(
            "POST",
            "/api/webhooks/lemonsqueezy",
            raw_hook,
            {"X-Signature": "deadbeef", "X-Event-Name": "order_created"},
        )
        self.assertEqual(st_bad, 401)
        self.assertEqual(bad_res["code"], "invalid_webhook_signature")

        # Valid webhook (server-to-server without Origin header) settles exactly +100 credits
        sig = self._sign_webhook(raw_hook)
        st_ok, ok_res = self._req(
            "POST",
            "/api/webhooks/lemonsqueezy",
            raw_hook,
            {"X-Signature": sig, "X-Event-Name": "order_created"},
        )
        self.assertEqual(st_ok, 200)
        self.assertTrue(ok_res["applied"])
        self.assertEqual(ok_res["order"]["status"], "paid")
        self.assertEqual(ok_res["credits"], 120)  # 20 signup bonus + 100 topup

        # Replay of identical webhook is strictly idempotent
        st_dup, dup_res = self._req(
            "POST",
            "/api/webhooks/lemonsqueezy",
            raw_hook,
            {"X-Signature": sig, "X-Event-Name": "order_created"},
        )
        self.assertEqual(st_dup, 200)
        self.assertTrue(dup_res["duplicate"])

        # Buyer A sees paid order in order history; Buyer B sees empty
        st_list_a, list_a = self._req("GET", "/api/billing/orders", headers={"Authorization": f"Bearer {self.tok_a}"})
        st_list_b, list_b = self._req("GET", "/api/billing/orders", headers={"Authorization": f"Bearer {self.tok_b}"})
        self.assertEqual(st_list_a, 200)
        self.assertEqual(len(list_a["orders"]), 1)
        self.assertEqual(list_a["orders"][0]["status"], "paid")
        self.assertEqual(st_list_b, 200)
        self.assertEqual(list_b["orders"], [])

        # Refund webhook reverses credits
        refund_payload = {
            "meta": {
                "event_name": "order_refunded",
                "webhook_id": "wh_evt_2",
                "custom_data": {"order_id": order_id, "user_id": custom_uid},
            },
            "data": {
                "type": "orders",
                "id": "998877",
                "attributes": {
                    "store_id": 521462,
                    "status": "refunded",
                    "refunded": True,
                    "test_mode": True,
                    "first_order_item": {"variant_id": 100002},
                },
            },
        }
        raw_refund = json.dumps(refund_payload).encode("utf-8")
        st_ref, ref_res = self._req(
            "POST",
            "/api/webhooks/lemonsqueezy",
            raw_refund,
            {"X-Signature": self._sign_webhook(raw_refund), "X-Event-Name": "order_refunded"},
        )
        self.assertEqual(st_ref, 200)
        self.assertTrue(ref_res["applied"])
        self.assertEqual(ref_res["order"]["status"], "refunded")
        self.assertEqual(ref_res["credits"], 20)

    def test_return_sync_verifies_identifier_ownership_and_prevents_hijack(self) -> None:
        with patch("backend.billing._lemon_api_request") as mock_api:
            mock_api.return_value = {
                "data": {"id": "chk_a", "attributes": {"url": "https://handraw.lemonsqueezy.com/checkout/chk_a"}}
            }
            _, chk_a = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
            mock_api.return_value = {
                "data": {"id": "chk_b", "attributes": {"url": "https://handraw.lemonsqueezy.com/checkout/chk_b"}}
            }
            _, chk_b = self._req(
                "POST",
                "/api/billing/checkout",
                {"packId": "pack_50"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
            )

        ord_a = chk_a["order"]["id"]
        ord_b = chk_b["order"]["id"]

        # Buyer B cannot touch Buyer A's order
        st_idor, _ = self._req(
            "POST",
            f"/api/billing/orders/{ord_a}/sync",
            {"providerOrderId": "777", "providerOrderIdentifier": "ident-777"},
            {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(st_idor, 404)

        # Buyer B guessing providerOrderId=777 with wrong identifier fails 403
        with patch("backend.billing._lemon_api_request") as mock_api:
            mock_api.return_value = {
                "data": {
                    "id": "777",
                    "attributes": {
                        "store_id": 521462,
                        "identifier": "real-uuid-777",
                        "order_number": 7007,
                        "status": "paid",
                        "refunded": False,
                        "test_mode": True,
                        "created_at": "2099-01-01T00:00:00Z",
                        "first_order_item": {"variant_id": 100001},
                    },
                }
            }
            st_wrong_ident, _ = self._req(
                "POST",
                f"/api/billing/orders/{ord_b}/sync",
                {"providerOrderId": "777", "providerOrderIdentifier": "wrong-uuid"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
            )
            self.assertEqual(st_wrong_ident, 403)

            # Buyer A syncs with authentic identifier -> succeeds and settles +50 credits
            st_sync, sync_res = self._req(
                "POST",
                f"/api/billing/orders/{ord_a}/sync",
                {"providerOrderId": "777", "providerOrderIdentifier": "real-uuid-777"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_a}"},
            )
            self.assertEqual(st_sync, 200)
            self.assertTrue(sync_res["applied"])
            self.assertEqual(sync_res["credits"], 70)
            self.assertEqual(sync_res["order"]["status"], "paid")

            # Even if Buyer B somehow got real-uuid-777 afterward, provider_order_id cannot settle twice (409)
            st_dup_claim, dup_claim = self._req(
                "POST",
                f"/api/billing/orders/{ord_b}/sync",
                {"providerOrderId": "777", "providerOrderIdentifier": "real-uuid-777"},
                {"Origin": "http://trusted.test", "Authorization": f"Bearer {self.tok_b}"},
            )
            self.assertEqual(st_dup_claim, 409)
            self.assertEqual(dup_claim["code"], "provider_order_conflict")

    def test_rejects_test_mode_webhook_when_configured_live(self) -> None:
        self.cfg_payload["test_mode"] = False
        self.cfg_path.write_text(json.dumps(self.cfg_payload, ensure_ascii=False), encoding="utf-8")
        hook_payload = {
            "meta": {"event_name": "order_created", "webhook_id": "wh_live_guard"},
            "data": {
                "type": "orders",
                "id": "888",
                "attributes": {"store_id": 521462, "status": "paid", "test_mode": True},
            },
        }
        raw = json.dumps(hook_payload).encode("utf-8")
        st, body = self._req(
            "POST",
            "/api/webhooks/lemonsqueezy",
            raw,
            {"X-Signature": self._sign_webhook(raw), "X-Event-Name": "order_created"},
        )
        self.assertEqual(st, 400)
        self.assertEqual(body["code"], "test_mode_mismatch")

    def test_lemon_api_request_retries_once_on_transient_transport_error(self) -> None:
        import io
        import urllib.error
        from backend.billing import _lemon_api_request

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"data": {"id": "store_ok"}}).encode("utf-8")

        attempts = {"count": 0}

        def flaky_open(req, timeout=20.0):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise urllib.error.URLError("SSL: UNEXPECTED_EOF_WHILE_READING")
            return _FakeResp()

        with patch("backend.billing.open_url", side_effect=flaky_open):
            res = _lemon_api_request("GET", "/v1/stores/521462", self.api_key)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(res["data"]["id"], "store_ok")


if __name__ == "__main__":
    unittest.main()
