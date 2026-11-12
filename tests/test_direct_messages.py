"""Unit tests for Handraw Direct Messaging (Phase 1A).

Covers:
- Anti-replay (same clientMessageId writes only once)
- Read cursor monotonically advances and cannot exceed existing messages
- Non-member and admin cannot read or mark other people's DMs
- Rate limits (10/min, 100/day, 10 new contacts/day)
- Blocking stops sending both ways while preserving history; unblock restores
- Unread totals calculation (/api/messages/unread)
- Body length boundaries and content validation (pure text, 1-2000 non-whitespace chars, no HTML/media)
- Abuse reporting for DM messages
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from tests.legacy_database import Database
from backend.db import utc_now_iso
from backend.messaging import (
    block_user,
    get_messages_unread_summary,
    list_dm_conversations,
    list_dm_messages,
    mark_dm_read,
    send_direct_message,
    unblock_user,
)
from tests.legacy_database import init_legacy_database
from backend.services import ServiceError, register_user, submit_abuse_report


class DirectMessagingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_dm.db"
        self.db = init_legacy_database(self.db_path)

        # Register users for testing
        self.alice, _ = register_user(self.db, "alice_dm", "password123")
        self.bob, _ = register_user(self.db, "bob_dm", "password123")
        self.charlie, _ = register_user(self.db, "charlie_dm", "password123")
        self.admin, _ = register_user(self.db, "admin_dm", "password123")
        # Elevate admin role
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin["id"],))
        self.admin["role"] = "admin"

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_anti_replay_same_client_message_id(self):
        """Same clientMessageId should only write once and return the existing message."""
        payload = {
            "recipientId": self.bob["id"],
            "body": "Hello Bob, this is message 1",
            "clientMessageId": "cm_test_anti_replay_001",
        }
        res1 = send_direct_message(self.db, self.alice, payload)
        self.assertTrue(res1["ok"])
        self.assertFalse(res1.get("replayed", False))
        msg_id_1 = res1["message"]["id"]

        # Resend with exact same clientMessageId
        res2 = send_direct_message(self.db, self.alice, payload)
        self.assertTrue(res2["ok"])
        self.assertTrue(res2.get("replayed", True))
        self.assertEqual(res2["message"]["id"], msg_id_1)

        # Verify only 1 row exists in dm_messages
        count = self.db.get_conn().execute(
            "SELECT COUNT(*) FROM dm_messages WHERE sender_id = ? AND client_message_id = ?",
            (self.alice["id"], "cm_test_anti_replay_001"),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_read_cursor_monotonically_advances(self):
        """Read cursor must only advance and cannot exceed existing messages in conversation."""
        # Alice sends 3 messages to Bob
        m1 = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Msg 1"})
        m2 = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Msg 2"})
        m3 = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Msg 3"})
        conv_id = m1["conversationId"]
        id1 = m1["message"]["id"]
        id2 = m2["message"]["id"]
        id3 = m3["message"]["id"]

        # Bob cannot mark a non-existent message ID (or exceeding max)
        with self.assertRaises(ServiceError) as ctx:
            mark_dm_read(self.db, self.bob, conv_id, {"messageId": id3 + 999})
        self.assertEqual(ctx.exception.status, 400)

        # Bob marks read up to m2
        read_res = mark_dm_read(self.db, self.bob, conv_id, {"messageId": id2})
        self.assertTrue(read_res["ok"])
        self.assertEqual(read_res["lastReadMessageId"], id2)

        # Bob attempts to regress cursor to m1 -> cursor remains at m2
        regress_res = mark_dm_read(self.db, self.bob, conv_id, {"messageId": id1})
        self.assertTrue(regress_res["ok"])
        self.assertEqual(regress_res["lastReadMessageId"], id2)

        cursor_in_db = self.db.get_conn().execute(
            "SELECT last_read_message_id FROM dm_members WHERE conversation_id = ? AND user_id = ?",
            (conv_id, self.bob["id"]),
        ).fetchone()[0]
        self.assertEqual(cursor_in_db, id2)

        # Alice checks messages: m1 and m2 should show isRead=True, m3 should show isRead=False
        alice_view = list_dm_messages(self.db, self.alice, conv_id, {})
        msgs = {m["id"]: m for m in alice_view["messages"]}
        self.assertTrue(msgs[id1]["isRead"])
        self.assertTrue(msgs[id2]["isRead"])
        self.assertFalse(msgs[id3]["isRead"])

    def test_non_member_and_admin_cannot_read_or_mark_dms(self):
        """Only conversation participants may read or mark read. Admin has no bypass."""
        m = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Private chat"})
        conv_id = m["conversationId"]

        # Third-party user Charlie
        with self.assertRaises(ServiceError) as ctx:
            list_dm_messages(self.db, self.charlie, conv_id, {})
        self.assertEqual(ctx.exception.status, 403)

        with self.assertRaises(ServiceError) as ctx:
            mark_dm_read(self.db, self.charlie, conv_id, {"messageId": m["message"]["id"]})
        self.assertEqual(ctx.exception.status, 403)

        # Admin user
        with self.assertRaises(ServiceError) as ctx:
            list_dm_messages(self.db, self.admin, conv_id, {})
        self.assertEqual(ctx.exception.status, 403)

        with self.assertRaises(ServiceError) as ctx:
            mark_dm_read(self.db, self.admin, conv_id, {"messageId": m["message"]["id"]})
        self.assertEqual(ctx.exception.status, 403)

    def test_rate_limits_minute_day_and_contacts(self):
        """Enforces 10 msgs/min, 100 msgs/day, and 10 new contacts/day."""
        # Test 10 msgs/minute
        for i in range(10):
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": f"Rapid msg {i}"})

        # 11th in the same minute should be rejected
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Over 10/min"})
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "rate_limited_minute")

        # Test 100 msgs/day
        # Simulate moving past 1-minute window by updating created_at on previous 10 messages
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE dm_messages SET created_at = datetime(created_at, '-2 minutes') WHERE sender_id = ?",
                (self.alice["id"],),
            )

        # Now insert up to 100 messages total for today
        current_count = self.db.get_conn().execute(
            "SELECT COUNT(*) FROM dm_messages WHERE sender_id = ?", (self.alice["id"],)
        ).fetchone()[0]
        needed = 100 - current_count
        now_iso = utc_now_iso()
        with self.db.transaction() as tx:
            for i in range(needed):
                tx.execute(
                    "INSERT INTO dm_messages (conversation_id, sender_id, body, client_message_id, created_at) "
                    "VALUES (1, ?, ?, ?, datetime('now', '-5 minutes'))",
                    (self.alice["id"], f"bulk_{i}", f"cm_bulk_{i}"),
                )

        # 101st message today should be rejected with 429
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Over 100/day"})
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "rate_limited_daily")

        # Test 10 new contacts/day using Charlie as sender
        created_users = []
        for i in range(12):
            u, _ = register_user(self.db, f"contact_{i}", "password123")
            created_users.append(u)

        # Charlie messages 10 new people
        for i in range(10):
            res = send_direct_message(self.db, self.charlie, {"recipientId": created_users[i]["id"], "body": "Hi there"})
            self.assertTrue(res["ok"])

        # Age Charlie's previous messages past the 1-minute window
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE dm_messages SET created_at = datetime(created_at, '-2 minutes') WHERE sender_id = ?",
                (self.charlie["id"],),
            )

        # Charlie messaging an existing contact (e.g. contact_0 again) is allowed
        res_existing = send_direct_message(self.db, self.charlie, {"recipientId": created_users[0]["id"], "body": "Hi again"})
        self.assertTrue(res_existing["ok"])

        # Charlie messaging 11th new person is rejected
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.charlie, {"recipientId": created_users[10]["id"], "body": "New contact 11"})
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.code, "rate_limited_contacts")

    def test_block_and_unblock_interactions(self):
        """Blocking prevents sending messages in either direction while keeping past history readable."""
        # Send initial message
        m = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Friendly hello"})
        conv_id = m["conversationId"]

        # Alice blocks Bob
        b_res = block_user(self.db, self.alice, {"userId": self.bob["id"]})
        self.assertTrue(b_res["ok"])
        self.assertTrue(b_res["blocked"])

        # Bob cannot send to Alice
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.bob, {"recipientId": self.alice["id"], "body": "Can you hear me?"})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "dm_blocked")

        # Alice cannot send to Bob either while blocked
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Still blocked"})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "dm_blocked")

        # History is still readable by both
        alice_hist = list_dm_messages(self.db, self.alice, conv_id, {})
        bob_hist = list_dm_messages(self.db, self.bob, conv_id, {})
        self.assertEqual(len(alice_hist["messages"]), 1)
        self.assertEqual(len(bob_hist["messages"]), 1)
        self.assertTrue(alice_hist["conversation"]["isBlocked"])
        self.assertTrue(bob_hist["conversation"]["isBlocked"])

        # Alice unblocks Bob
        unblock_res = unblock_user(self.db, self.alice, str(self.bob["id"]))
        self.assertTrue(unblock_res["ok"])
        self.assertTrue(unblock_res["unblocked"])

        # Sending is now restored
        m2 = send_direct_message(self.db, self.bob, {"recipientId": self.alice["id"], "body": "Thanks for unblocking!"})
        self.assertTrue(m2["ok"])

    def test_unread_total_calculation(self):
        """Unread total = notifications + direct + broadcasts (broadcasts=0). Opening list does not auto-mark read."""
        # Alice sends 2 DMs to Bob
        send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Msg A"})
        m2 = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Msg B"})
        conv_id = m2["conversationId"]

        # Insert 1 notification for Bob
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO notifications (user_id, kind, title, created_at) VALUES (?, 'system', 'Test Notice', ?)",
                (self.bob["id"], utc_now_iso()),
            )

        # Check unread count
        unread = get_messages_unread_summary(self.db, self.bob)
        self.assertEqual(unread["notifications"], 1)
        self.assertEqual(unread["direct"], 2)
        self.assertEqual(unread["broadcasts"], 0)
        self.assertEqual(unread["total"], 3)

        # Listing conversations does NOT mark read
        list_res = list_dm_conversations(self.db, self.bob, {})
        self.assertEqual(list_res["conversations"][0]["unreadCount"], 2)
        unread_after_list = get_messages_unread_summary(self.db, self.bob)
        self.assertEqual(unread_after_list["direct"], 2)

        # Bob reads only message 1
        m1_id = self.db.get_conn().execute(
            "SELECT id FROM dm_messages WHERE conversation_id = ? ORDER BY id ASC LIMIT 1",
            (conv_id,),
        ).fetchone()[0]
        mark_dm_read(self.db, self.bob, conv_id, {"messageId": m1_id})

        # Direct unread decreases from 2 to 1
        unread_after_partial = get_messages_unread_summary(self.db, self.bob)
        self.assertEqual(unread_after_partial["direct"], 1)
        self.assertEqual(unread_after_partial["total"], 2)

        # Bob reads message 2
        mark_dm_read(self.db, self.bob, conv_id, {"messageId": m2["message"]["id"]})
        unread_after_all = get_messages_unread_summary(self.db, self.bob)
        self.assertEqual(unread_after_all["direct"], 0)
        self.assertEqual(unread_after_all["total"], 1)

    def test_body_length_and_content_boundaries(self):
        """Validates 1-2000 non-whitespace chars, pure text only (no HTML or markdown media)."""
        # Empty or only whitespace
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "   \n\t  "})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_body_length")

        # 1 non-whitespace char
        r1 = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "   A   "})
        self.assertTrue(r1["ok"])

        # 2000 non-whitespace chars
        r2000 = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "X" * 2000})
        self.assertTrue(r2000["ok"])

        # 2001 non-whitespace chars
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "X" * 2001})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_body_length")

        # HTML injection attempt
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Hello <script>alert(1)</script>"})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "html_not_allowed")

        # Markdown image attempt
        with self.assertRaises(ServiceError) as ctx:
            send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Look at this ![image](http://example.com/pic.png)"})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "media_not_allowed")

    def test_report_abuse_dm_message(self):
        """Abuse report integration for dm_message target type."""
        m = send_direct_message(self.db, self.alice, {"recipientId": self.bob["id"], "body": "Suspicious offer"})
        msg_id = m["message"]["id"]

        # Non-participant Charlie cannot report
        with self.assertRaises(ServiceError) as ctx:
            submit_abuse_report(self.db, self.charlie, {
                "targetType": "dm_message",
                "targetId": str(msg_id),
                "reason": "Spam",
            })
        self.assertEqual(ctx.exception.status, 403)

        # Recipient Bob can report
        rep = submit_abuse_report(self.db, self.bob, {
            "targetType": "dm_message",
            "targetId": str(msg_id),
            "reason": "垃圾广告",
            "detail": "私信发送了垃圾信息",
        })
        self.assertTrue(rep["ok"])

        # Verify report in database
        r_row = self.db.get_conn().execute(
            "SELECT * FROM reports WHERE target_type = 'dm_message' AND target_id = ?",
            (str(msg_id),),
        ).fetchone()
        self.assertIsNotNone(r_row)
        self.assertEqual(r_row["reporter_username"], "bob_dm")
        self.assertIn("Suspicious offer", r_row["detail"])


class DirectMessagingHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        import hashlib
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from backend.server import HandrawRequestHandler

        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "http_dm_test.db"
        self.env = patch.dict(
            os.environ,
            {
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(root / "uploads"),
                "HANDRAW_GENERATED_DIR": str(root / "generated"),
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
                "HANDRAW_ENABLE_RECHARGE": "0",
            },
        )
        self.env.start()
        self.db = init_legacy_database(self.db_path)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        self.httpd.allow_demo_routes = True  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

        self.u1, _ = register_user(self.db, "u1_alice", "password123")
        self.u2, _ = register_user(self.db, "u2_bob", "password123")
        self.u3, _ = register_user(self.db, "u3_charlie", "password123")
        self.admin_user, _ = register_user(self.db, "u4_admin", "password123")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (self.admin_user["id"],))

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.db.close()
        self.env.stop()
        self.temp_dir.cleanup()

    def _login(self, username: str) -> str:
        status, headers, _ = self.request(
            "POST",
            "/api/auth/login",
            {"account": username, "password": "password123"},
            {"Origin": "http://trusted.test"},
        )
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie", "")
        return cookie.split(";", 1)[0]

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        import urllib.request
        import urllib.error
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_http_dm_full_lifecycle(self):
        # 1. Unread count as guest -> 0
        s, _, r = self.request("GET", "/api/messages/unread")
        self.assertEqual(s, 200)
        d = json.loads(r)
        self.assertEqual(d["total"], 0)

        # 2. Post DM without login -> 401
        s, _, _ = self.request("POST", "/api/dm/messages", {"recipientId": self.u2["id"], "body": "test"})
        self.assertEqual(s, 401)

        # 3. Alice logs in and sends message to Bob
        cookie_alice = self._login("u1_alice")
        s, _, r = self.request(
            "POST",
            "/api/dm/messages",
            {"recipientId": self.u2["id"], "body": "Hello Bob over HTTP!", "clientMessageId": "http_cm_1"},
            headers={"Cookie": cookie_alice, "Origin": "http://trusted.test"},
        )
        self.assertEqual(s, 200)
        msg_resp = json.loads(r)
        self.assertTrue(msg_resp["ok"])
        conv_id = msg_resp["conversationId"]
        msg_id = msg_resp["message"]["id"]

        # 4. Bob logs in and checks unread -> 1
        cookie_bob = self._login("u2_bob")
        s, _, r = self.request("GET", "/api/messages/unread", headers={"Cookie": cookie_bob})
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(r)["direct"], 1)

        # 5. Bob lists conversations
        s, _, r = self.request("GET", "/api/dm/conversations", headers={"Cookie": cookie_bob})
        self.assertEqual(s, 200)
        convs = json.loads(r)["conversations"]
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["unreadCount"], 1)

        # 6. Charlie tries to list messages of Alice and Bob's conversation -> 403
        cookie_charlie = self._login("u3_charlie")
        s, _, _ = self.request("GET", f"/api/dm/conversations/{conv_id}/messages", headers={"Cookie": cookie_charlie})
        self.assertEqual(s, 403)

        # 7. Admin also gets 403 (no admin bypass)
        cookie_admin = self._login("u4_admin")
        s, _, _ = self.request("GET", f"/api/dm/conversations/{conv_id}/messages", headers={"Cookie": cookie_admin})
        self.assertEqual(s, 403)

        # 8. Mutually exclusive before & after
        s, _, _ = self.request("GET", f"/api/dm/conversations/{conv_id}/messages?before=100&after=1", headers={"Cookie": cookie_bob})
        self.assertEqual(s, 400)

        # 9. Bob lists messages and marks read
        s, _, r = self.request("GET", f"/api/dm/conversations/{conv_id}/messages", headers={"Cookie": cookie_bob})
        self.assertEqual(s, 200)
        msgs = json.loads(r)["messages"]
        self.assertEqual(len(msgs), 1)

        s, _, r = self.request(
            "POST",
            f"/api/dm/conversations/{conv_id}/read",
            {"messageId": msg_id},
            headers={"Cookie": cookie_bob, "Origin": "http://trusted.test"},
        )
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(r)["lastReadMessageId"], msg_id)

        # 10. Bob's unread is now 0
        s, _, r = self.request("GET", "/api/messages/unread", headers={"Cookie": cookie_bob})
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(r)["direct"], 0)

        # 11. Alice blocks Bob
        s, _, r = self.request(
            "POST",
            "/api/dm/blocks",
            {"userId": self.u2["id"]},
            headers={"Cookie": cookie_alice, "Origin": "http://trusted.test"},
        )
        self.assertEqual(s, 200)
        self.assertTrue(json.loads(r)["blocked"])

        # 12. Bob cannot send to Alice while blocked -> 403
        s, _, r = self.request(
            "POST",
            "/api/dm/messages",
            {"recipientId": self.u1["id"], "body": "Blocked message", "clientMessageId": "http_cm_2"},
            headers={"Cookie": cookie_bob, "Origin": "http://trusted.test"},
        )
        self.assertEqual(s, 403)
        self.assertEqual(json.loads(r)["code"], "dm_blocked")

        # 13. Alice unblocks Bob
        s, _, r = self.request(
            "DELETE",
            f"/api/dm/blocks/{self.u2['id']}",
            headers={"Cookie": cookie_alice, "Origin": "http://trusted.test"},
        )
        self.assertEqual(s, 200)
        self.assertTrue(json.loads(r)["unblocked"])

        # 14. Bob can send to Alice again
        s, _, r = self.request(
            "POST",
            "/api/dm/messages",
            {"recipientId": self.u1["id"], "body": "I can message you now", "clientMessageId": "http_cm_3"},
            headers={"Cookie": cookie_bob, "Origin": "http://trusted.test"},
        )
        self.assertEqual(s, 200)

        # 15. Report abuse on DM message
        s, _, r = self.request(
            "POST",
            "/api/reports",
            {"targetType": "dm_message", "targetId": str(msg_id), "reason": "不良信息", "detail": "涉嫌广告"},
            headers={"Cookie": cookie_bob, "Origin": "http://trusted.test"},
        )
        self.assertEqual(s, 200)
        self.assertTrue(json.loads(r)["ok"])



if __name__ == "__main__":
    unittest.main()
