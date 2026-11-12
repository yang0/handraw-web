"""P2 integration regression: growth cohort, security signals and OAuth binding.

All network-based provider calls are mocked. Tests use isolated PostgreSQL storage.
"""
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from backend.seed import ensure_seeded
from tests.postgres_support import open_isolated_postgres
from backend.services import ServiceError, login_user, register_user, update_my_profile
from backend import p2_growth, p2_oauth, p2_google


class FakeHandler:
    def __init__(self, db, user=None):
        self.db = db
        self.user = user
        self.headers = {"User-Agent": "Mozilla/5.0 Chrome/128.0 Linux",
                        "Cookie": ""}
        self.client_address = ("127.0.0.1", 1234)
        self.headers_out = []
    def _current_user(self, required=False):
        if required and self.user is None:
            raise ServiceError("请先登录", status=401)
        return self.user
    def _cookie_for_token(self, token):
        return "handraw_sid=" + token
    def _send_json(self, obj, status=200, set_cookie=None):
        self.response_json = obj
        self.response_status = status
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
    def send_response(self, status):
        self.response_status = status
    def send_header(self, name, value):
        self.headers_out.append((name, value))
    def end_headers(self):
        pass
    def get_header(self, name):
        return [v for k,v in self.headers_out if k == name]


class P2IdentityGrowthTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {
            "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_PRIVATE_STORAGE": tmp,
            "HANDRAW_GITHUB_CLIENT_ID": "test-id",
            "HANDRAW_GITHUB_CLIENT_SECRET": "test-secret",
            "HANDRAW_GITHUB_CALLBACK_URL": "http://localhost:3080/api/auth/github/callback",
            "HANDRAW_GOOGLE_CLIENT_ID": "google-test-client",
            "HANDRAW_GOOGLE_CLIENT_SECRET": "google-test-secret",
            "HANDRAW_GOOGLE_CALLBACK_URL": "http://localhost:3080/api/auth/google/callback",
        }))
        self.db = open_isolated_postgres(self)
        ensure_seeded(self.db)
        self.seed = dict(self.db.get_conn().execute(
            "SELECT * FROM users WHERE username='su_editorial'"
        ).fetchone())

    def _begin_oauth(self, mode="login", user=None):
        handler = FakeHandler(self.db, user)
        p2_oauth.start_github(handler, mode)
        self.assertEqual(handler.response_status, 303)
        url = handler.get_header("Location")[0]
        self.assertTrue(url.startswith("https://github.com/login/oauth/authorize?"))
        state = parse_qs(urlsplit(url).query)["state"][0]
        cookie = [x for x in handler.get_header("Set-Cookie") if "handraw_oauth_nonce=" in x][0]
        handler.headers["Cookie"] = cookie.split(";",1)[0]
        handler.headers_out.clear()
        return handler, state

    def test_registration_milestones_and_activation_cohorts(self):
        created, _ = register_user(self.db, "fresh_p2", "StrongPass2026!", "fresh-p2@example.test")
        uid = created["id"]
        conn = self.db.get_conn()
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM growth_events WHERE user_id=? AND event_name='first_collection'",
            (uid,),
        ).fetchone()[0], 0)
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO collections(user_id,bucket,target_id,created_at) VALUES(?,?,?,?)",
                (uid, "works", "example-p2", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
        events = conn.execute(
            "SELECT event_name FROM growth_events WHERE user_id=?", (uid,)
        ).fetchall()
        self.assertIn("first_collection", [x["event_name"] for x in events])
        p2_growth.record_visit(self.db, created)
        p2_growth.record_visit(self.db, created)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM growth_events WHERE user_id=? AND event_name='site_visit'", (uid,)
        ).fetchone()[0], 1)
        report = p2_growth.growth_report(self.db, {"role":"admin"}, days=30)
        self.assertTrue(report["summary"]["registered"] >= 1)
        self.assertTrue(report["summary"]["activated7d"] >= 1)
        self.assertGreater(report["summary"]["activationRate"], 0)
        with self.assertRaises(ServiceError):
            p2_growth.growth_report(self.db, {"role":"user"})

    def test_draft_publish_transition_creates_activation_milestones(self):
        created, _ = register_user(self.db, "draft_p2", "StrongPass2026!", "draft-p2@example.test")
        uid = created["id"]
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO works(id,author_username,author_name,title,prompt,status,
                                     published_at_ms,created_at,updated_at)
                   VALUES(?,?,?,?,?,'draft',?,?,?)""",
                ("p2-draft-work",created["username"],created["display_name"],
                 "待发布作品","测试提示词",int(datetime.now(timezone.utc).timestamp()*1000),
                 created_at,created_at)
            )
            tx.execute("UPDATE works SET status='published' WHERE id='p2-draft-work'")
            tx.execute(
                """INSERT INTO forum_topics(id,category,category_label,title,
                                             author_username,author_name,summary,status,
                                             published_at_ms,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,'draft',?,?,?)""",
                ("p2-draft-topic","experience","体验","首次发布的帖子",
                 created["username"],created["display_name"],"帖子简介",
                 int(datetime.now(timezone.utc).timestamp()*1000),created_at,created_at)
            )
            tx.execute("UPDATE forum_topics SET status='published' WHERE id='p2-draft-topic'")
        events = {x["event_name"] for x in self.db.get_conn().execute(
            "SELECT event_name FROM growth_events WHERE user_id=?", (uid,)
        ).fetchall()}
        self.assertIn("first_work", events)
        self.assertIn("first_topic", events)

    def test_cohort_retention_and_activation_use_utc_and_first_event(self):
        kept, _ = register_user(self.db, "cohort_kept", "StrongPass2026!")
        late, _ = register_user(self.db, "cohort_late", "StrongPass2026!")
        conn = self.db.get_conn()
        conn.execute("SET TIME ZONE 'Pacific/Auckland'")
        for user in (kept, late):
            conn.execute("UPDATE users SET created_at = '2030-01-02T12:00:00Z' WHERE id = ?", (user["id"],))
        conn.execute("""
            INSERT INTO verified_emails (user_id, email, verified_at)
            VALUES (?, 'verified@example.test', '2030-01-04T00:00:00Z')
        """, (kept["id"],))
        conn.executemany("""
            INSERT INTO growth_events (user_id, event_name, event_day, happened_at)
            VALUES (?, ?, ?, ?)
        """, [
            (kept["id"], "first_collection", "2030-01-03", "2030-01-03T00:00:00Z"),
            (kept["id"], "first_generation", "2030-01-06", "2030-01-06T00:00:00Z"),
            (kept["id"], "site_visit", "2030-01-09", "2030-01-09T00:00:00Z"),
            (late["id"], "first_generation", "2030-01-09", "2030-01-09T12:00:01Z"),
            (late["id"], "site_visit", "2030-01-10", "2030-01-10T00:00:00Z"),
        ])
        with patch.object(p2_growth, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2030, 1, 10, 23, 59, tzinfo=timezone.utc)
            report = p2_growth.growth_report(self.db, {"role": "admin"}, days=7)
            self.assertEqual(report["cohorts"], [])
            report = p2_growth.growth_report(self.db, {"role": "admin"}, days=8)
        self.assertEqual(report["cohorts"], [{
            "day": "2030-01-02", "registered": 2, "verified": 1,
            "activated_7d": 1, "eligible_d7": 2, "retained_d7": 1,
        }])
        self.assertEqual(report["summary"]["retentionD7Rate"], 50)
        self.assertEqual(conn.execute("""
            SELECT event_day FROM growth_events WHERE user_id = ? AND event_name = 'email_verified'
        """, (kept["id"],)).fetchone()[0], "2030-01-04")

    def test_native_generation_milestone_is_created_once_per_day(self):
        user, _ = register_user(self.db, "generation_p2", "StrongPass2026!")
        conn = self.db.get_conn()
        conn.execute("""
            INSERT INTO generation_runs (id, user_id, source, external_run_id, expected_count, created_at, updated_at)
            VALUES ('milestone-run', ?, 'web', 'milestone-external', 2, '2026-01-01T00:00:00Z', '')
        """, (user["id"],))
        query = "SELECT COUNT(*) FROM growth_events WHERE user_id = ? AND event_name = 'first_generation'"
        self.assertEqual(conn.execute(query, (user["id"],)).fetchone()[0], 0)
        conn.execute("UPDATE generation_runs SET status = 'partial' WHERE id = 'milestone-run'")
        conn.execute("UPDATE generation_runs SET status = 'success' WHERE id = 'milestone-run'")
        self.assertEqual(conn.execute(query, (user["id"],)).fetchone()[0], 1)

    def test_new_browser_environment_alert_is_not_sent_on_first_login(self):
        created, _ = register_user(self.db, "browser_p2", "StrongPass2026!", "browser@example.test")
        self.assertFalse(p2_growth.record_login(self.db, created, "Chrome/129.0 Windows"))
        self.assertFalse(p2_growth.record_login(self.db, created, "Chrome/130.0 Windows"))
        self.assertTrue(p2_growth.record_login(self.db, created, "Firefox/129.0 macOS"))
        self.assertEqual(self.db.get_conn().execute(
            "SELECT count(*) FROM security_devices WHERE user_id=?", (created["id"],)
        ).fetchone()[0], 2)
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='security'",
            (created["id"],)
        ).fetchone()[0], 1)

    def test_github_flow_rejects_missing_configuration_and_state_replay(self):
        with patch.dict(os.environ, {"HANDRAW_GITHUB_CLIENT_SECRET": ""}):
            self.assertIsNone(p2_oauth.github_config())
            with self.assertRaises(ServiceError):
                p2_oauth.start_github(FakeHandler(self.db), "login")
        handler, state = self._begin_oauth()
        with patch("backend.p2_oauth.fetch_github_identity",
                   return_value={"subject":"90001","login":"p2user","email":"p2-social@example.test"}):
            p2_oauth.complete_github(handler, {"state":[state], "code":["mock-code"]})
        self.assertEqual(handler.response_status, 303)
        self.assertEqual(handler.get_header("Location")[-1], "/?view=oauth-register")
        signup_cookie = next(x for x in handler.get_header("Set-Cookie") if x.startswith("handraw_oauth_signup="))
        handler.headers["Cookie"] = signup_cookie.split(";",1)[0]
        status = p2_oauth.signup_status(handler)
        self.assertEqual(status["providerLogin"], "p2user")
        p2_oauth.finish_signup(handler, {"username":"my_new_social", "displayName":"不可变的首次昵称"})
        self.assertEqual(handler.response_status, 200)
        link = self.db.get_conn().execute(
            "SELECT user_id FROM oauth_identities WHERE provider='github' AND provider_user_id='90001'"
        ).fetchone()
        self.assertIsNotNone(link)
        new_user = dict(self.db.get_conn().execute(
            "SELECT * FROM users WHERE id=?", (link["user_id"],)
        ).fetchone())
        self.assertEqual(new_user["display_name"], "不可变的首次昵称")
        with self.assertRaises(ServiceError) as locked:
            update_my_profile(self.db, new_user, {"displayName":"试图更改"})
        self.assertEqual(locked.exception.code, "nickname_locked")
        with self.assertRaises(ServiceError) as denied:
            p2_oauth.complete_github(handler, {"state":[state], "code":["mock-code"]})
        self.assertEqual(denied.exception.code, "oauth_state_invalid")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM verified_emails WHERE user_id=?", (link["user_id"],)
        ).fetchone()[0], 1)

    def _begin_google(self, mode="login", user=None):
        handler = FakeHandler(self.db, user)
        p2_google.start_google(handler, mode)
        self.assertEqual(handler.response_status, 303)
        url = handler.get_header("Location")[-1]
        self.assertTrue(url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertIn("code_challenge", params)
        state = params["state"][0]
        cookie = next(x for x in handler.get_header("Set-Cookie")
                      if x.startswith("handraw_google_nonce="))
        handler.headers["Cookie"] = cookie.split(";",1)[0]
        handler.headers_out.clear()
        return handler, state

    def test_google_first_signup_requires_nickname_confirmation_and_prevents_replay(self):
        handler, state = self._begin_google()
        with patch("backend.p2_google.fetch_google_identity",
                   return_value={"subject":"10390011","login":"Google Test","email":"google-p2@example.test"}):
            p2_google.complete_google(handler, {"state":[state],"code":["mock-google-code"]})
        self.assertEqual(handler.get_header("Location")[-1], "/?view=oauth-register")
        cookie = next(x for x in handler.get_header("Set-Cookie")
                      if x.startswith("handraw_oauth_signup="))
        handler.headers["Cookie"] = cookie.split(";",1)[0]
        claim = p2_oauth.signup_status(handler)
        self.assertEqual(claim["provider"], "Google")
        self.assertEqual(claim["verifiedEmail"], "google-p2@example.test")
        p2_oauth.finish_signup(handler, {"username":"google_p2","displayName":"首次 Google 昵称"})
        row = self.db.get_conn().execute(
            "SELECT * FROM users WHERE username='google_p2'"
        ).fetchone()
        self.assertEqual(row["display_name"], "首次 Google 昵称")
        binding = self.db.get_conn().execute(
            "SELECT provider FROM oauth_identities WHERE user_id=?", (row["id"],)
        ).fetchone()
        self.assertEqual(binding["provider"], "google")
        with self.assertRaises(ServiceError):
            p2_oauth.finish_signup(handler, {"username":"google_p2_replay"})
        with self.assertRaises(ServiceError) as denied:
            p2_google.complete_google(handler, {"state":[state],"code":["mock-google-code"]})
        self.assertEqual(denied.exception.code, "oauth_state_invalid")

    def test_google_email_collision_requires_explicit_link_and_password_to_unlink(self):
        handler, state = self._begin_google()
        with patch("backend.p2_google.fetch_google_identity",
                   return_value={"subject":"10390012","login":"Other","email":self.seed["email"]}):
            with self.assertRaises(ServiceError) as denied:
                p2_google.complete_google(handler, {"state":[state],"code":["mock-google-code"]})
        self.assertEqual(denied.exception.code, "oauth_link_required")
        handler, state = self._begin_google("link", self.seed)
        with patch("backend.p2_google.fetch_google_identity",
                   return_value={"subject":"10390012","login":"Other","email":self.seed["email"]}):
            p2_google.complete_google(handler, {"state":[state],"code":["mock-google-code"]})
        self.assertEqual(self.db.get_conn().execute(
            "SELECT user_id FROM oauth_identities WHERE provider='google' AND provider_user_id='10390012'"
        ).fetchone()["user_id"], self.seed["id"])
        with self.assertRaises(ServiceError):
            p2_google.unlink_google(self.db, self.seed, "incorrect")
        self.assertTrue(p2_google.unlink_google(self.db, self.seed, "handraw123")["ok"])

    def test_google_state_browser_mismatch_stops_before_token_exchange(self):
        handler, state = self._begin_google()
        handler.headers["Cookie"] = "handraw_google_nonce=wrong"
        with patch("backend.p2_google.fetch_google_identity") as identity:
            with self.assertRaises(ServiceError) as denied:
                p2_google.complete_google(handler, {"state":[state],"code":["mock-google-code"]})
            identity.assert_not_called()
        self.assertEqual(denied.exception.code, "oauth_state_invalid")

    def test_github_email_collision_requires_explicit_linking(self):
        handler, state = self._begin_oauth()
        with patch("backend.p2_oauth.fetch_github_identity",
                   return_value={"subject":"90002","login":"someone","email":self.seed["email"]}):
            with self.assertRaises(ServiceError) as denied:
                p2_oauth.complete_github(handler, {"state":[state], "code":["mock-code"]})
        self.assertEqual(denied.exception.code, "oauth_link_required")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM oauth_identities WHERE provider_user_id='90002'"
        ).fetchone()[0], 0)
        bind, state = self._begin_oauth("link", self.seed)
        with patch("backend.p2_oauth.fetch_github_identity",
                   return_value={"subject":"90002","login":"someone","email":self.seed["email"]}):
            p2_oauth.complete_github(bind, {"state":[state],"code":["mock-code"]})
        self.assertEqual(self.db.get_conn().execute(
            "SELECT user_id FROM oauth_identities WHERE provider_user_id='90002'"
        ).fetchone()["user_id"], self.seed["id"])
        with self.assertRaises(ServiceError):
            p2_oauth.unlink_github(self.db, self.seed, "wrong-password")
        self.assertTrue(p2_oauth.unlink_github(self.db, self.seed, "handraw123")["ok"])

    def test_callback_requires_matching_browser_cookie(self):
        handler, state = self._begin_oauth()
        handler.headers["Cookie"] = "handraw_oauth_nonce=forged"
        with self.assertRaises(ServiceError) as denied:
            p2_oauth.complete_github(handler, {"state":[state], "code":["mock-code"]})
        self.assertEqual(denied.exception.code, "oauth_state_invalid")
        self.assertEqual(self.db.get_conn().execute(
            "SELECT COUNT(*) FROM oauth_flows WHERE state_hash=?", (p2_oauth._digest(state),)
        ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
