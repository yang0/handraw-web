"""Recovery tokens, notifications and author editing in an isolated database."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.server import init_database
from backend import features
from backend.services import ServiceError, login_user, add_comment_to_work
from backend.security import verify_password


class AccountFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HANDRAW_DEMO_MODE":"1","HANDRAW_PRIVATE_STORAGE":self.temp.name})
        self.env.start()
        self.db = init_database(Path(self.temp.name)/"account-test.db")
        self.a = dict(self.db.get_conn().execute("SELECT * FROM users WHERE username='su_editorial'").fetchone())
        self.b = dict(self.db.get_conn().execute("SELECT * FROM users WHERE username='momo_design'").fetchone())
        self.ready = patch("backend.features.mail_ready",return_value=True)
        self.ready.start()

    def tearDown(self):
        self.ready.stop();self.db.close();self.env.stop();self.temp.cleanup()

    def test_password_reset_single_use_revokes_all_sessions(self):
        login_user(self.db,self.a["username"],"handraw123")
        with patch("backend.features.send_account_mail") as send:
            result=features.request_account_mail(self.db,"password_reset",self.a["email"])
            self.assertTrue(result["ok"])
            token=send.call_args.args[2]
        raw=self.db.get_conn().execute("SELECT token_hash FROM account_action_tokens").fetchone()[0]
        self.assertNotEqual(token,raw)
        features.consume_account_token(self.db,"password_reset",token,"NewPassword2026!")
        stored=self.db.get_conn().execute("SELECT password_hash FROM users WHERE id=?",(self.a["id"],)).fetchone()[0]
        self.assertTrue(verify_password("NewPassword2026!",stored))
        self.assertEqual(0,self.db.get_conn().execute("SELECT count(*) FROM sessions WHERE user_id=?",(self.a["id"],)).fetchone()[0])
        with self.assertRaises(ServiceError):features.consume_account_token(self.db,"password_reset",token,"AnotherPass2026!")

    def test_verification_binds_to_email_and_expires(self):
        with patch("backend.features.send_account_mail") as send:
            features.request_account_mail(self.db,"verify_email",self.a["email"],self.a)
            token=send.call_args.args[2]
        features.consume_account_token(self.db,"verify_email",token)
        self.assertTrue(features.account_status(self.db,self.a)["emailVerified"])
        changed={**self.a,"email":"changed@example.com"}
        self.assertFalse(features.account_status(self.db,changed)["emailVerified"])
        with self.assertRaises(ServiceError):features.consume_account_token(self.db,"password_reset",token,"NewPassword2026!")

    def test_failed_mail_does_not_leave_a_valid_token_or_rate_limit(self):
        with patch("backend.features.send_account_mail",side_effect=ServiceError("unavailable",status=503)):
            with self.assertRaises(ServiceError):features.request_account_mail(self.db,"password_reset",self.a["email"])
        self.assertEqual(0,self.db.get_conn().execute("SELECT count(*) FROM account_action_tokens").fetchone()[0])

    def test_recovery_reply_does_not_reveal_unknown_account(self):
        with patch("backend.features.send_account_mail") as send:
            found=features.request_account_mail(self.db,"password_reset",self.a["email"])
            unknown=features.request_account_mail(self.db,"password_reset","absent@example.invalid")
        self.assertEqual(found,unknown)
        self.assertEqual(send.call_count,1)

    def test_comment_notification_is_private_and_generated_from_real_event(self):
        work=self.db.get_conn().execute("SELECT id FROM works WHERE author_username=? AND status='published' LIMIT 1",(self.a["username"],)).fetchone()
        before=features.list_notifications(self.db,self.a)["unread"]
        add_comment_to_work(self.db,self.b,work["id"],"实际评论事件验证")
        self.assertEqual(before+1,features.list_notifications(self.db,self.a)["unread"])
        a_ids={n["id"] for n in features.list_notifications(self.db,self.a)["items"]}
        b_ids={n["id"] for n in features.list_notifications(self.db,self.b)["items"]}
        self.assertFalse(a_ids & b_ids)

    def test_only_author_can_edit_work_without_changing_price_or_rewards(self):
        work=self.db.get_conn().execute("SELECT * FROM works WHERE author_username=? LIMIT 1",(self.a["username"],)).fetchone()
        balance=self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id=?",(self.a["id"],)).fetchone()[0]
        with self.assertRaises(ServiceError) as ctx:
            features.edit_owned_content(self.db,self.a,"works",work["id"],{"title":"作者修改后的作品标题","prompt":"实际完整的创作提示词","price":9999})
        self.assertEqual(400, ctx.exception.status)
        self.assertEqual("work_price_not_allowed", ctx.exception.code)
        features.edit_owned_content(self.db,self.a,"works",work["id"],{"title":"作者修改后的作品标题","prompt":"实际完整的创作提示词"})
        changed=self.db.get_conn().execute("SELECT * FROM works WHERE id=?",(work["id"],)).fetchone()
        self.assertEqual(changed["price"],0)
        self.assertEqual(changed["title"],"作者修改后的作品标题")
        self.assertEqual(balance,self.db.get_conn().execute("SELECT balance FROM wallets WHERE user_id=?",(self.a["id"],)).fetchone()[0])
        with self.assertRaises(ServiceError) as denied:features.edit_owned_content(self.db,self.b,"works",work["id"],{"title":"越权修改作品标题"})
        self.assertEqual(403,denied.exception.status)

    def test_account_export_excludes_credentials_and_other_users(self):
        user = self.a
        class Handler:
            db = self.db
            def _current_user(self, required=True):
                return user
            def _send_json(self, payload, set_cookie=None):
                self.response = payload
        handler = Handler()
        self.assertTrue(features.handle_feature_get(handler, "/api/account/export", {}))
        exported = handler.response
        self.assertTrue(exported["ok"])
        self.assertEqual(exported["profile"]["username"], user["username"])
        self.assertNotIn("password_hash", json.dumps(exported))
        self.assertNotIn("discourse_salt", json.dumps(exported))
        self.assertTrue(all(w["id"] for w in exported["works"]))
        self.assertTrue(all(t["id"] for t in exported["forumTopics"]))

    def test_account_closure_and_reactivation_routes_are_disabled(self):
        class Handler:
            db = self.db
            def _current_user(self, required=True):
                return self.user
            user = self.a
        handler = Handler()
        self.assertFalse(features.handle_feature_post(
            handler, "/api/account/close",
            {"confirmation": self.a["username"], "currentPassword": "handraw123"}
        ))
        self.assertFalse(features.handle_feature_post(
            handler, "/api/auth/request-reactivation",
            {"email": self.a["email"]}
        ))
        self.assertFalse(features.handle_feature_post(
            handler, "/api/auth/confirm-reactivation",
            {"token": "invalid"}
        ))

    def test_author_cannot_sneak_script_into_topic_edit(self):
        topic=self.db.get_conn().execute("SELECT id FROM forum_topics WHERE author_username=? LIMIT 1",(self.a["username"],)).fetchone()
        features.edit_owned_content(self.db,self.a,"topics",topic["id"],{"title":"修改自己的帖子标题","body":'<p>保留正常文字</p><script>alert(1)</script><img src="javascript:evil()" onerror="alert(2)">'})
        changed=features._owned_content(self.db,self.a,"topics",topic["id"])
        self.assertNotIn("<script",changed["summary"])
        self.assertNotIn("javascript:",changed["summary"])
        self.assertNotIn("onerror",changed["summary"])


if __name__=="__main__":unittest.main()
