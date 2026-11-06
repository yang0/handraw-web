"""Account identity basics: nickname immutability, verified email changes, safe avatars."""
import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.server import init_database
from backend import features
from backend.avatar_identity import avatar_dir, avatar_file_for_path, save_avatar, reset_avatar
from backend.security import verify_password
from backend.services import ServiceError, login_user, register_user, update_my_profile, build_boot_payload


class AccountIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "HANDRAW_DEMO_MODE": "1", "HANDRAW_PRIVATE_STORAGE": self.temp.name
        })
        self.env.start()
        self.db = init_database(Path(self.temp.name) / "test-account-identity.db")
        self.user = dict(self.db.get_conn().execute(
            "SELECT * FROM users WHERE username='su_editorial'"
        ).fetchone())

    def tearDown(self):
        self.db.close()
        self.env.stop()
        self.temp.cleanup()

    def test_nickname_is_immutable_after_registration_including_legacy_unlocked(self):
        before = self.user["display_name"]
        with self.assertRaises(ServiceError) as denied:
            update_my_profile(self.db, self.user, {"displayName": "不能再修改的昵称"})
        self.assertEqual(denied.exception.code, "nickname_locked")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT display_name FROM users WHERE id=?", (self.user["id"],)
        ).fetchone()[0], before)

        created, _ = register_user(self.db, "nickname_no_change", "Passw0rdSecure!",
                                    "nickname-no-change@example.org")
        self.assertEqual(created["nickname_locked"], 1)
        self.assertEqual(created["display_name"], "nickname_no_change")
        with self.assertRaises(ServiceError) as denied:
            update_my_profile(self.db, created, {"displayName": "注册后更改"})
        self.assertEqual(denied.exception.code, "nickname_locked")
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET nickname_locked=0,nickname_changed_at=0 WHERE id=?", (created["id"],))
        with self.assertRaises(ServiceError):
            update_my_profile(self.db, created, {"displayName": "旧状态也不可更改"})
        result = update_my_profile(self.db, created, {"bio": "简介仍可编辑"})
        self.assertEqual(result["boot"]["user"]["bio"], "简介仍可编辑")
        self.assertEqual(result["boot"]["user"]["displayName"], "nickname_no_change")

    def test_direct_email_update_rejected_and_verify_new_address_before_switch(self):
        old = self.user["email"]
        with self.assertRaises(ServiceError) as denied:
            update_my_profile(self.db, self.user, {"email": "changed@example.net"})
        self.assertEqual(denied.exception.code, "email_verification_required")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT email FROM users WHERE id=?", (self.user["id"],)
        ).fetchone()[0], old)

        login_user(self.db, self.user["username"], "handraw123")
        with patch("backend.features.mail_ready", return_value=True), patch(
            "backend.features.send_account_mail"
        ) as sender:
            response = features.request_email_change(
                self.db, self.user, "new-owner@example.net", "handraw123"
            )
            self.assertTrue(response["ok"])
            token = sender.call_args.args[2]
            self.assertEqual(sender.call_args.args[:2], ("new-owner@example.net", "email_change"))
        self.assertEqual(self.db.get_conn().execute(
            "SELECT email FROM users WHERE id=?", (self.user["id"],)
        ).fetchone()[0], old)
        features.consume_account_token(self.db, "email_change", token)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT email FROM users WHERE id=?", (self.user["id"],)
        ).fetchone()[0], "new-owner@example.net")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT count(*) FROM sessions WHERE user_id=?", (self.user["id"],)
        ).fetchone()[0], 0)
        with self.assertRaises(ServiceError):
            features.consume_account_token(self.db, "email_change", token)

    def test_password_change_revokes_other_sessions(self):
        _, sess = login_user(self.db, self.user["username"], "handraw123")
        login_user(self.db, self.user["username"], "handraw123")
        current = {**self.user, "_session_token": sess}
        result = update_my_profile(self.db, current, {
            "newPassword": "NewStrongPassword2026!", "currentPassword": "handraw123"
        })
        self.assertTrue(result["sessionsRevoked"])
        rows = self.db.get_conn().execute(
            "SELECT token FROM sessions WHERE user_id=?", (self.user["id"],)
        ).fetchall()
        self.assertEqual(len(rows), 1, "other browser session revoked")
        self.assertTrue(verify_password("NewStrongPassword2026!",
            self.db.get_conn().execute("SELECT password_hash FROM users WHERE id=?",
                                       (self.user["id"],)).fetchone()[0]))

    def test_avatar_is_reencoded_public_webp_and_resettable(self):
        buf = io.BytesIO()
        Image.new("RGB", (480, 300), "#bc7660").save(buf, "PNG")
        data = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        result = save_avatar(self.db, self.user, data)
        self.assertTrue(result["avatarUrl"].startswith("/avatars/"))
        path = avatar_file_for_path(result["avatarUrl"])
        self.assertIsNotNone(path)
        with Image.open(path) as pic:
            self.assertEqual(pic.format, "WEBP")
            self.assertEqual(pic.size, (320, 320))
        self.assertIsNone(avatar_file_for_path("/avatars/../../secrets.txt"))
        refreshed = dict(self.db.get_conn().execute(
            "SELECT * FROM users WHERE id=?", (self.user["id"],)
        ).fetchone())
        boot = build_boot_payload(self.db, refreshed)
        self.assertEqual(boot["user"]["avatarUrl"], result["avatarUrl"])
        self.assertEqual(boot["creatorAvatars"][self.user["username"]], result["avatarUrl"])
        self.assertTrue(reset_avatar(self.db, self.user)["ok"])
        self.assertEqual(self.db.get_conn().execute(
            "SELECT avatar_url FROM users WHERE id=?", (self.user["id"],)
        ).fetchone()[0], "")
        with self.assertRaises(ServiceError):
            save_avatar(self.db, self.user, "data:image/svg+xml;base64,PHN2Zz4=")


if __name__ == "__main__":
    unittest.main()
