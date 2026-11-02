"""Comprehensive integration tests for Handraw Web 2.0 full-stack platform & Admin Console.

Runs entirely against an isolated temporary SQLite WAL database (never touching production or .local DB).
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.server import HandrawRequestHandler, init_database

ROOT = Path(__file__).resolve().parents[1]
SKILL_SPEC = importlib.util.spec_from_file_location(
    "personal_library_v2_check",
    ROOT / "skill-addon/scripts/personal_library.py",
)
skill_mod = importlib.util.module_from_spec(SKILL_SPEC)
assert SKILL_SPEC and SKILL_SPEC.loader
SKILL_SPEC.loader.exec_module(skill_mod)


class SessionClient:
    """Stateful HTTP JSON client with isolated CookieJar for multi-persona testing."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(
        self,
        method: str,
        path: str,
        body: dict | list | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        req_headers = {"Accept": "application/json"}
        data_bytes = None
        if body is not None:
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data_bytes,
            headers=req_headers,
            method=method.upper(),
        )
        try:
            with self.opener.open(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(raw) if raw else {}
            except Exception:
                parsed = {"error": raw}
            return err.code, parsed


class HandrawV2PlatformAndAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "isolated_v2_test.db"
        self.uploads_dir = Path(self.temp_dir.name) / "uploads"
        self.generated_dir = Path(self.temp_dir.name) / "generated"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)

        self.env_patch = patch.dict(
            os.environ,
            {
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_DB_PATH": str(self.db_path),
                "HANDRAW_UPLOADS_DIR": str(self.uploads_dir),
                "HANDRAW_GENERATED_DIR": str(self.generated_dir),
            },
        )
        self.env_patch.start()

        self.db = init_database(self.db_path)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.channel_role = "main"  # type: ignore[attr-defined]
        self.httpd.db = self.db  # type: ignore[attr-defined]
        port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server_thread.join(timeout=5)
        self.db.close()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def client(self, username: str | None = None, password: str = "handraw123") -> SessionClient:
        c = SessionClient(self.base_url)
        if username:
            code, res = c.request("POST", "/api/auth/login", {"account": username, "password": password})
            self.assertEqual(code, 200, f"Login failed for {username}: {res}")
        return c

    def collect(self, result):
        """Drive the result to its public state.

        Works publish immediately (D-02), so there is nothing to drain: assert
        the row exists and that it did not enter the review queue.  Styles and
        layouts keep the two-vote gate, so they are still reviewed here.
        """
        from backend import curation as C
        from backend.services import register_user
        reviewers=[]
        for name in ('qa_collect_a','qa_collect_b'):
            row=self.db.get_conn().execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
            reviewers.append(dict(row) if row else register_user(self.db,name,'qa-password')[0])
        admin=dict(self.db.get_conn().execute("SELECT * FROM users WHERE username='yang0'").fetchone())
        C.grant_access(self.db,admin,{'usernames':[r['username'] for r in reviewers],'kinds':['work','style','layout'],'action':'grant','reason':'isolated fixtures'})

        if result.get('status')=='published':
            self.assertIsNone(C.review_queue(self.db,reviewers[0])['assignment'],
                              "a published work must not re-enter the review queue")
            row=self.db.get_conn().execute('SELECT * FROM works WHERE id=?',(result['workId'],)).fetchone()
            self.assertIsNotNone(row, "work row must exist immediately after publishing")
            return result

        published=None
        for reviewer in reviewers:
            task=C.review_queue(self.db,reviewer)['assignment']
            self.assertEqual(task['topicId'],result['topicId'])
            vote=C.vote(self.db,reviewer,{'assignmentId':task['assignmentId'],'decision':'approve'})
            published=vote.get('published') or published
        return published

    def test_01_public_works_seo_and_blackbox_protection(self) -> None:
        guest = self.client()
        code, boot = guest.request("GET", "/api/boot")
        self.assertEqual(code, 200)
        self.assertFalse(boot["loggedIn"])
        self.assertGreaterEqual(len(boot["works"]), 34, "Anonymous users & SEO crawlers must see published works")
        self.assertGreaterEqual(boot["totalWorksCount"], 34)
        self.assertGreater(boot["totalCheersCount"], 100)
        self.assertTrue(len(boot["assetCounts"]) > 10)
        self.assertTrue(len(boot["publicCreators"]) >= 5)

        # Verify leaderboard time horizons (Weekly <=7d, Monthly 8~30d, All-time >30d)
        import time as _time
        now_ms = int(_time.time() * 1000)
        day_ms = 24 * 3600 * 1000
        week_works = [w for w in boot["works"] if (now_ms - int(w.get("publishedAtMs") or 0)) <= 7 * day_ms]
        month_only_works = [w for w in boot["works"] if 7 * day_ms < (now_ms - int(w.get("publishedAtMs") or 0)) <= 30 * day_ms]
        older_works = [w for w in boot["works"] if (now_ms - int(w.get("publishedAtMs") or 0)) > 30 * day_ms]
        self.assertGreaterEqual(len(week_works), 5, "Should have active works in the past 7 days")
        self.assertGreaterEqual(len(month_only_works), 5, "Should have works in 8~30d monthly cohort")
        self.assertGreaterEqual(len(older_works), 5, "Should have historical works >30d for All-Time Hall of Fame")

        # Works are all free (Issue #29): price is 0 and prompt is not masked by pricing
        self.assertTrue(all(int(w.get("price") or 0) == 0 for w in boot["works"]))
        self.assertTrue(all(not w.get("promptMasked") for w in boot["works"]))

        raw_boot = json.dumps(boot, ensure_ascii=False)
        self.assertNotIn("secret_blackbox_prompt", raw_boot)

        # Verify SEO endpoints: robots.txt, sitemap.xml, and SSR HTML metadata + JSON-LD + work cards
        with urllib.request.urlopen(f"{self.base_url}/robots.txt", timeout=5) as r_rob:
            rob_txt = r_rob.read().decode("utf-8")
            self.assertIn("Allow: /", rob_txt)
            self.assertIn("Sitemap:", rob_txt)

        with urllib.request.urlopen(f"{self.base_url}/sitemap.xml", timeout=5) as r_map:
            xml_txt = r_map.read().decode("utf-8")
            self.assertIn("?view=works", xml_txt)
            self.assertIn(boot["works"][0]["id"], xml_txt)

        sample_w = boot["works"][0]
        with urllib.request.urlopen(f"{self.base_url}/?view=works&work={sample_w['id']}", timeout=5) as r_seo:
            seo_html = r_seo.read().decode("utf-8")
            self.assertIn("application/ld+json", seo_html)
            self.assertIn("VisualArtwork", seo_html)
            self.assertIn(sample_w["title"], seo_html)
            self.assertIn("hw-seo-work-item", seo_html)

        # Verify standalone Work Detail, Asset Detail, and Personal Homepage SSR SEO URLs
        with urllib.request.urlopen(f"{self.base_url}/?view=work&id={sample_w['id']}", timeout=5) as r_wpage:
            wpage_html = r_wpage.read().decode("utf-8")
            self.assertIn("VisualArtwork", wpage_html)
            self.assertIn(sample_w["title"], wpage_html)

        # Verify legacy asset detail 302 redirect to /t/FA-001 per Phase 3b-12
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def http_error_302(self, req, fp, code, msg, headers):
                return fp
        _opener = urllib.request.build_opener(_NoRedirect)
        with _opener.open(f"{self.base_url}/?view=asset&id=FA-001", timeout=5) as r_apage:
            self.assertEqual(r_apage.status, 302)
            self.assertEqual(r_apage.headers.get("Location"), "/t/FA-001")

        with urllib.request.urlopen(f"{self.base_url}/?view=profile&user=yang0", timeout=5) as r_ppage:
            ppage_html = r_ppage.read().decode("utf-8")
            self.assertIn("ProfilePage", ppage_html)
            self.assertIn("个人主页", ppage_html)

    def test_02_register_referral_and_frozen_session_revocation(self) -> None:
        admin = self.client("yang0")
        _, before_boot = admin.request("GET", "/api/boot")
        yang_before = before_boot["credits"]

        new_user = self.client()
        code, reg = new_user.request(
            "POST",
            "/api/auth/register",
            {
                "username": "new_creator_99",
                "displayName": "阿林手绘",
                "email": "new99@example.com",
                "password": "Password123!",
                "inviteCode": "yang0",
            },
        )
        self.assertEqual(code, 200, reg)
        # +20 welcome + +10 invitee = 30
        self.assertEqual(reg["boot"]["credits"], 30)

        _, after_boot = admin.request("GET", "/api/boot")
        self.assertEqual(after_boot["credits"], yang_before + 15)

        # Freeze the new user from Admin Console -> active session must immediately be revoked
        _, users_res = admin.request("GET", "/api/admin/users?q=new_creator_99")
        target_uid = users_res["items"][0]["id"]
        code_frz, _ = admin.request(
            "POST",
            f"/api/admin/users/{target_uid}/update",
            {"status": "frozen", "reason": "自动化风控测试冻结"},
        )
        self.assertEqual(code_frz, 200)

        _, frozen_boot = new_user.request("GET", "/api/boot")
        self.assertFalse(frozen_boot["loggedIn"])
        code_relogin, _ = new_user.request("POST", "/api/auth/login", {"account": "new_creator_99", "password": "Password123!"})
        self.assertEqual(code_relogin, 403)

    def test_03_blackbox_protection_and_reviewer_masking(self) -> None:
        admin = self.client("yang0")
        reviewer = self.client("reviewer_su")

        _, admin_boot = admin.request("GET", "/api/boot")
        self.assertNotIn("secret_blackbox_prompt", json.dumps(admin_boot, ensure_ascii=False))

        # Reviewer sees masked blackbox prompt in /api/admin/catalog
        code_rev, rev_cat = reviewer.request("GET", "/api/admin/catalog?sourceType=exclusive")
        self.assertEqual(code_rev, 200)
        fx1_rev = next(x for x in rev_cat["items"] if x["code"] == "FX-001")
        self.assertIn("仅超级管理员", fx1_rev["secretBlackboxPrompt"])

        # Admin sees full plaintext blackbox prompt and can update it
        code_adm, adm_cat = admin.request("GET", "/api/admin/catalog?sourceType=exclusive")
        self.assertEqual(code_adm, 200)
        fx1_adm = next(x for x in adm_cat["items"] if x["code"] == "FX-001")
        self.assertNotIn("仅超级管理员", fx1_adm["secretBlackboxPrompt"])
        self.assertTrue(len(fx1_adm["secretBlackboxPrompt"]) > 15)

        # Skill-Addon endpoint strictly blocks exclusive blackbox export (403)
        tok_raw = "hwt_test_token_yang0_bb_export"
        tok_hash = hashlib.sha256(tok_raw.encode("utf-8")).hexdigest()
        self.db.get_conn().execute(
            "INSERT OR REPLACE INTO api_tokens (id, user_id, name, scopes, token_hash, created_at) "
            "VALUES ('tok_bb_test', (SELECT id FROM users WHERE username = 'yang0'), 'Test', '[\"library\"]', ?, '2026-10-31T00:00:00Z')",
            (tok_hash,),
        )
        code_sk, _ = admin.request(
            "GET",
            "/studio/api/assets/FX-001/content",
            headers={"Authorization": f"Bearer {tok_raw}"},
        )
        self.assertEqual(code_sk, 403)

    def test_04_wallet_checkin_redeem_tip_unlock_and_admin_refund_clawback(self) -> None:
        su = self.client("su_editorial")
        _, b0 = su.request("GET", "/api/boot")
        c0 = b0["credits"]

        # 1) Daily Check-in (+5, idempotent same day)
        code1, ck1 = su.request("POST", "/api/wallet/checkin", {})
        self.assertEqual(code1, 200)
        self.assertEqual(ck1["credits"], c0 + 5)
        code2, _ = su.request("POST", "/api/wallet/checkin", {})
        self.assertEqual(code2, 400)

        # 2) Redeem Code HANDRAW2026 (+30, single use per user)
        code_rd, rd = su.request("POST", "/api/wallet/redeem", {"code": "HANDRAW2026"})
        self.assertEqual(code_rd, 200)
        self.assertEqual(rd["added"], 30)
        self.assertEqual(rd["credits"], c0 + 35)
        code_rd_dup, _ = su.request("POST", "/api/wallet/redeem", {"code": "HANDRAW2026"})
        self.assertEqual(code_rd_dup, 400)

        # 3) 100% Direct Micro-Tip from su_editorial -> yang0
        admin = self.client("yang0")
        yang_work = next(w for w in b0["works"] if w["author"] == "yang0")
        _, yang_b0 = admin.request("GET", "/api/boot")
        code_tip, tip_res = su.request("POST", "/api/interactions/tip", {"targetType": "work", "targetId": yang_work["id"], "amount": 4})
        self.assertEqual(code_tip, 200)
        self.assertEqual(tip_res["credits"], c0 + 31)
        _, yang_b1 = admin.request("GET", "/api/boot")
        self.assertEqual(yang_b1["credits"], yang_b0["credits"] + 4)

        # 4) Works cannot be priced or unlocked (Issue #29); Forum Paid Reading (80% split) + Admin Refund & Royalty Clawback
        code_w_bad, res_w_bad = admin.request(
            "POST",
            "/api/works",
            {
                "title": "付费精调配方测试图",
                "images": ["/images/poster-demo-autumn-equinox.webp"],
                "styles": ["FA-001"],
                "layout": "SC-001",
                "price": 10,
                "notes": "这是用于测试的完整创作说明，详细记录测试过程",
                "prompt": "机密高阶手绘提示词内容_888",
            },
        )
        self.assertEqual(code_w_bad, 400)
        self.assertEqual(res_w_bad.get("code"), "work_price_not_allowed")

        _, pub_w = admin.request(
            "POST",
            "/api/works",
            {
                "title": "开源精调配方测试图",
                "images": ["/images/poster-demo-autumn-equinox.webp"],
                "styles": ["FA-001"],
                "layout": "SC-001",
                "price": 0,
                "notes": "这是用于测试的完整创作说明，详细记录测试过程",
                "prompt": "开源高阶手绘提示词内容_888",
            },
        )
        self.collect(pub_w)
        free_wid = pub_w["workId"]

        # Su attempts to unlock work -> rejected with 400 and does NOT deduct credits
        _, su_pre_work_ul = su.request("GET", "/api/boot")
        code_work_ul, _ = su.request("POST", "/api/unlocks", {"targetId": free_wid, "targetType": "work"})
        self.assertEqual(code_work_ul, 400)
        _, su_post_work_ul = su.request("GET", "/api/boot")
        self.assertEqual(su_post_work_ul["credits"], su_pre_work_ul["credits"])

        # Paid forum topic unlock (80% split)
        paid_body = (
            "<p>前序公开试读章节</p>"
            "<div class=\"hw-paywall-divider\" data-paywall-price=\"10\">"
            "<div class=\"hw-paywall-divider-pill\"><span class=\"hw-paywall-pill-text\">此处以下为 10✦ 专属核心章节</span></div>"
            "</div>"
            "<p>机密高阶手绘提示词内容_888</p>"
        )
        code_tp, tp_res = admin.request(
            "POST",
            "/api/forum/topics",
            {
                "title": "付费经验分享测试帖",
                "category": "experience",
                "publishMode": "paid",
                "price": 10,
                "bodyHtml": paid_body,
            },
        )
        self.assertEqual(code_tp, 200)
        paid_topic_id = tp_res["topic"]["id"]

        _, yang_before_sale = admin.request("GET", "/api/boot")
        _, su_before_buy = su.request("GET", "/api/boot")

        code_ul, ul_res = su.request("POST", "/api/unlocks", {"targetId": paid_topic_id})
        self.assertEqual(code_ul, 200, ul_res)
        self.assertIn("机密高阶手绘提示词内容_888", ul_res["unlockedContent"])
        self.assertEqual(ul_res["credits"], su_before_buy["credits"] - 10)
        _, yang_after_sale = admin.request("GET", "/api/boot")
        self.assertEqual(yang_after_sale["credits"], yang_before_sale["credits"] + 8)

        # Admin refunds unlock order -> buyer gets +10, author gets -8 clawback
        _, ul_list = admin.request("GET", "/api/admin/unlocks?status=settled")
        order = next(x for x in ul_list["items"] if x["targetId"] == paid_topic_id)
        code_ref, _ = admin.request("POST", f"/api/admin/unlocks/{order['id']}/refund", {"reason": "测试订单全额退单与分成追回"})
        self.assertEqual(code_ref, 200)

        _, su_after_refund = su.request("GET", "/api/boot")
        _, yang_after_refund = admin.request("GET", "/api/boot")
        self.assertEqual(su_after_refund["credits"], su_before_buy["credits"])
        self.assertEqual(yang_after_refund["credits"], yang_before_sale["credits"])
        self.assertNotIn(paid_topic_id, su_after_refund["unlockedIds"])

    def test_05_pioneer_first_share_and_honor_tier_upgrade(self) -> None:
        fresh = self.client()
        fresh.request(
            "POST",
            "/api/auth/register",
            {"username": "pioneer_tester", "displayName": "开荒画师", "email": "pio@example.com", "password": "Password123!"},
        )
        _, b0 = fresh.request("GET", "/api/boot")
        c0 = b0["credits"]

        # Publish on an unpopulated style code -> base +5 + pioneer +10 = +15
        code_w, res_w = fresh.request(
            "POST",
            "/api/works",
            {
                "title": "荒地开垦首晒测试",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styles": ["FA-013"],
                "layout": "SC-001",
                "notes": "荒地开垦首晒测试创作说明实测心得记录",
                "prompt": "荒地首晒提示词",
            },
        )
        self.assertEqual(code_w, 200, res_w)
        # D-02: the work is live immediately and its reward lands right away.
        self.assertEqual(res_w['status'],'published')
        # Exact amounts, not "whatever the server reported".  FA-013 is an
        # unclaimed style, so this first share earns base +5 + pioneer +10, and
        # crossing the share threshold also triggers the +10 honour upgrade.
        self.assertEqual(res_w['reward'], 15, res_w)
        c_after_work = c0 + 5 + 10 + 10
        _,published_boot=fresh.request('GET','/api/boot')
        self.assertEqual(published_boot['credits'], c_after_work, "base + pioneer + honour upgrade must all apply")
        self.assertTrue(any(w['id']==res_w['workId'] for w in published_boot['works']))
        after_work=published_boot['credits']

        # Publish community style -> crosses total shares 1 -> 2 (rookie -> pioneer), earning +15 base + +10 honor upgrade!
        code_a, res_a = fresh.request(
            "POST",
            "/api/catalog/community",
            {
                "kind": "style",
                "name": "开荒测试水彩风",
                "group": "水彩插画",
                "image": "/images/individual/FA/FA-003.webp",
                "description": "柔和纸纹水彩",
                "definition": "高克重棉浆水彩纸肌理，通透湿画法边缘自然水痕晕染。",
            },
        )
        self.assertEqual(code_a, 200, res_a)
        self.assertEqual(res_a['status'],'pending')
        collected_asset=self.collect(res_a)
        self.assertTrue(collected_asset['upgradedBadge'])
        self.assertEqual(collected_asset['credits'],after_work+15+10)

    def test_06_forum_bounty_escrow_accept_and_admin_arbitration(self) -> None:
        su = self.client("su_editorial")
        lin = self.client("lin_sketch")
        admin = self.client("yang0")

        _, su_b0 = su.request("GET", "/api/boot")
        _, lin_b0 = lin.request("GET", "/api/boot")

        # 1) Create bounty topic (bounty=15 -> -15 escrow)
        code_t, t_res = su.request(
            "POST",
            "/api/forum/topics",
            {
                "category": "tuning",
                "title": "求助：水彩建筑透视边缘怎么控色？",
                "bounty": 15,
                "summary": "如题，悬赏 15 积分求调优参数建议！",
            },
        )
        self.assertEqual(code_t, 200, t_res)
        tid = t_res["topicId"]
        self.assertEqual(t_res["credits"], su_b0["credits"] - 15)

        # Responder replies (+2) and gets accepted (+15)
        code_r, r_res = lin.request("POST", f"/api/forum/topics/{tid}/replies", {"text": "建议挂载 FA-003 + 留白 high，亲测超稳！"})
        self.assertEqual(code_r, 200, r_res)
        rid = r_res["replyId"]

        code_acc, _ = su.request("POST", f"/api/forum/topics/{tid}/accept-bounty", {"replyId": rid})
        self.assertEqual(code_acc, 200)
        _, lin_b1 = lin.request("GET", "/api/boot")
        self.assertEqual(lin_b1["credits"], lin_b0["credits"] + 2 + 15)

        # 2) Second bounty topic -> Admin arbitrates refund_bounty
        _, su_b2 = su.request("GET", "/api/boot")
        _, t2_res = su.request(
            "POST",
            "/api/forum/topics",
            {"category": "tuning", "title": "无人应答的超期悬赏测试", "bounty": 20, "summary": "测试后台仲裁退回悬赏"},
        )
        tid2 = t2_res["topicId"]
        code_arb, _ = admin.request(
            "POST",
            f"/api/admin/topics/{tid2}/moderate",
            {"action": "refund_bounty", "reason": "超期无人解答，退回悬赏金"},
        )
        self.assertEqual(code_arb, 200)
        _, su_b3 = su.request("GET", "/api/boot")
        # 20 escrow fully refunded -> back to su_b2["credits"]
        self.assertEqual(su_b3["credits"], su_b2["credits"])

    def test_07_abuse_reports_auto_pause_and_moderation_restore(self) -> None:
        u1 = self.client("su_editorial")
        u2 = self.client("lin_sketch")
        u3 = self.client("momo_design")
        reviewer = self.client("reviewer_su")

        target_wid = "work_105"
        for cli in (u1, u2, u3):
            code, rep = cli.request("POST", "/api/reports", {"targetType": "work", "targetId": target_wid, "reason": "测试达到阈值自动暂停"})
            self.assertEqual(code, 200)

        self.assertTrue(rep["autoPaused"])
        _, adm_works = reviewer.request(f"GET", f"/api/admin/works?q={target_wid}")
        self.assertEqual(adm_works["items"][0]["status"], "paused")

        # Reviewer dismisses report with autoAction=True -> restores work to 'published'
        _, reps = reviewer.request("GET", "/api/admin/reports?status=open")
        rep_id = next(r["id"] for r in reps["items"] if r["targetId"] == target_wid)
        code_res, _ = reviewer.request(
            "POST",
            f"/api/admin/reports/{rep_id}/resolve",
            {"resolution": "dismissed", "note": "核查无违规，恢复上架", "autoAction": True},
        )
        self.assertEqual(code_res, 200)
        _, adm_works_after = reviewer.request("GET", f"/api/admin/works?q={target_wid}")
        self.assertEqual(adm_works_after["items"][0]["status"], "published")

    def test_08_rbac_boundaries_and_anti_self_review(self) -> None:
        normal = self.client("su_editorial")
        reviewer = self.client("reviewer_su")
        admin = self.client("yang0")

        # Normal user denied admin dashboard
        c_norm, _ = normal.request("GET", "/api/admin/dashboard")
        self.assertEqual(c_norm, 403)

        # Merged Operator/Reviewer allowed dashboard & redeem-codes, denied admin-only settings & discourse import
        c_rev_dash, _ = reviewer.request("GET", "/api/admin/dashboard")
        self.assertEqual(c_rev_dash, 200)
        c_code_ok, _ = reviewer.request("POST", "/api/admin/redeem-codes", {"code": "OPTEST88", "credits": 88})
        self.assertEqual(c_code_ok, 200)
        for admin_only_method, admin_only_path, payload in (
            ("POST", "/api/admin/settings", {"section": "economy", "values": {"daily_checkin_credits": 6}}),
            ("POST", "/api/admin/users/import-discourse", {"payload": "[]"}),
        ):
            code_den, _ = reviewer.request(admin_only_method, admin_only_path, payload)
            self.assertEqual(code_den, 403, f"Operator must be blocked from {admin_only_path}")

        # Anti-Self-Review: reviewer publishes own work, then tries to feature own work -> 403 self_review_forbidden
        _, own_pub = reviewer.request(
            "POST",
            "/api/works",
            {
                "title": "审核员自己的作品测试自审拦截",
                "images": ["/images/poster-demo-autumn-equinox.webp"],
                "styles": ["FA-001"],
                "notes": "审核员测试自审拦截的创作说明心得",
                "prompt": "审核员作品提示词",
            },
        )
        self.collect(own_pub)
        own_wid = own_pub["workId"]
        code_self, err_self = reviewer.request(
            "POST",
            f"/api/admin/works/{own_wid}/moderate",
            {"action": "feature", "reason": "试图给自己加精选"},
        )
        self.assertEqual(code_self, 403)
        self.assertEqual(err_self.get("code"), "self_review_forbidden")

        # Super-admin can review reviewer's work and leaves immutable audit_log
        code_adm, _ = admin.request(
            "POST",
            f"/api/admin/works/{own_wid}/moderate",
            {"action": "feature", "reason": "超管合规交叉审核加精"},
        )
        self.assertEqual(code_adm, 200)
        _, logs = admin.request("GET", "/api/admin/audit-logs?targetType=work")
        self.assertTrue(any(l["targetId"] == own_wid for l in logs["items"]))

    def test_09_studio_quota_credit_fallback_and_gateway_auto_refund(self) -> None:
        su = self.client("su_editorial")
        _, b0 = su.request("GET", "/api/boot")
        start_credits = b0["credits"]
        self.assertEqual(b0["freeQuotaRemaining"], 3)

        # 3 free daily generations
        for expected_rem in (2, 1, 0):
            code, res = su.request(
                "POST",
                "/api/studio/generate",
                {"prompt": "测试节气插画", "style1": "FX-001", "ratio": "3:4", "simulateGateway": "ok"},
            )
            self.assertEqual(code, 200, res)
            self.assertEqual(res["costType"], "free_quota")
            self.assertEqual(res["freeQuotaRemaining"], expected_rem)
            self.assertEqual(res["credits"], start_credits)

        # 4th generation falls back to 2 credits
        code4, res4 = su.request(
            "POST",
            "/api/studio/generate",
            {"prompt": "第4张消耗积分测试", "style1": "FX-001", "ratio": "3:4", "simulateGateway": "ok"},
        )
        self.assertEqual(code4, 200, res4)
        self.assertEqual(res4["costType"], "credits")
        self.assertEqual(res4["creditsSpent"], 2)
        self.assertEqual(res4["credits"], start_credits - 2)

        # 5th generation simulates gateway failure -> 502 + automatic 2-credit refund!
        code5, res5 = su.request(
            "POST",
            "/api/studio/generate",
            {"prompt": "网关异常自动退费测试", "style1": "FX-001", "ratio": "3:4", "simulateGateway": "fail"},
        )
        self.assertEqual(code5, 502)
        self.assertTrue(res5.get("refunded"))

        _, b_final = su.request("GET", "/api/boot")
        self.assertEqual(b_final["credits"], start_credits - 2)

    def test_10_discourse_user_migration_password_verification_and_upgrade(self) -> None:
        admin = self.client("yang0")
        raw_pw = "DiscourseLegacy#2026"
        salt = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
        # Authentic Discourse PBKDF2-HMAC-SHA256 (64,000 iterations)
        disc_hash = hashlib.pbkdf2_hmac("sha256", raw_pw.encode("utf-8"), salt.encode("utf-8"), 64000, dklen=32).hex()

        csv_payload = (
            "id,username,name,email,password_hash,salt,admin,moderator\n"
            f"808,legacy_painter,老社区画师,legacy808@handraw.org,{disc_hash},{salt},false,false\n"
        )
        code_imp, imp = admin.request(
            "POST",
            "/api/admin/users/import-discourse",
            {"payload": csv_payload, "migrationCredits": 60},
        )
        self.assertEqual(code_imp, 200, imp)
        self.assertEqual(imp["imported"], 1)

        # Login with original Discourse password -> succeeds & upgrades hash algorithm to pbkdf2_sha256
        migrated_cli = self.client("legacy_painter", password=raw_pw)
        _, m_boot = migrated_cli.request("GET", "/api/boot")
        self.assertTrue(m_boot["loggedIn"])
        self.assertEqual(m_boot["credits"], 60)

        row = self.db.get_conn().execute(
            "SELECT password_algo, password_hash FROM users WHERE username = 'legacy_painter'"
        ).fetchone()
        self.assertEqual(row["password_algo"], "pbkdf2_sha256")
        self.assertTrue(str(row["password_hash"]).startswith("pbkdf2_sha256$"))

    def test_11_skill_addon_personal_library_live_sync(self) -> None:
        # Ensure FA-005 is collected by yang0 so /studio/api/library exposes an official collected style
        admin = self.client("yang0")
        _, adm_boot = admin.request("GET", "/api/boot")
        if "FA-005" not in adm_boot["collections"]["styles"]:
            admin.request("POST", "/api/collections/toggle", {"bucket": "styles", "id": "FA-005", "title": "FA-005"})

        tok_sync = "hwt_test_token_yang0_sync"
        tok_sync_hash = hashlib.sha256(tok_sync.encode("utf-8")).hexdigest()
        self.db.get_conn().execute(
            "INSERT OR REPLACE INTO api_tokens (id, user_id, name, scopes, token_hash, created_at) "
            "VALUES ('tok_sync_test', (SELECT id FROM users WHERE username = 'yang0'), 'Test', '[\"library\"]', ?, '2026-10-31T00:00:00Z')",
            (tok_sync_hash,),
        )

        profile_dir = Path(self.temp_dir.name) / "skill_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "community_auth.json").write_text(
            json.dumps(
                {
                    "base_url": "https://handraw-style.com",
                    "username": "yang0",
                    "token": tok_sync,
                }
            ),
            encoding="utf-8",
        )
        lib = skill_mod.Library(profile_dir / "personal-library")

        real_urlopen = urllib.request.urlopen
        local_base = self.base_url

        class LocalBridgeResponse:
            def __init__(self, inner, orig_url: str) -> None:
                self._inner = inner
                self.url = orig_url

            def read(self, *args):
                return self._inner.read(*args)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self._inner.close()

        def bridged_open(req, timeout=35):
            orig_url = req.full_url
            parsed = urllib.parse.urlsplit(orig_url)
            rewritten = f"{local_base}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
            fwd = urllib.request.Request(rewritten, headers=dict(req.header_items()), method=req.get_method())
            return LocalBridgeResponse(real_urlopen(fwd, timeout=timeout), orig_url)

        with patch.dict(os.environ, {"HANDRAW_PROFILE_HOME": str(profile_dir)}):
            sc = skill_mod.Client()
            with patch.object(sc.opener, "open", side_effect=bridged_open):
                listing = sc.sync(lib, None)
                self.assertTrue(any(item["ref"] == "FA-005" for item in listing))
                imported = sc.sync(lib, "FA-005")
                self.assertEqual(imported["kind"], "style")
                self.assertEqual(imported["section"], "collected")
                self.assertIn("FA-005", imported["name"])

    def test_12_multi_role_consoles_user_crud_moderators_and_unified_social(self) -> None:
        admin = self.client("yang0")
        operator = self.client("ops_lin")
        reviewer = self.client("reviewer_su")
        board_mod = self.client("momo_design")  # Seeded moderator exclusively on 'assets' board
        creator = self.client("su_editorial")

        # 1. Role-Differentiated Management Profiles (/api/admin/permissions)
        c_adm, p_adm = admin.request("GET", "/api/admin/permissions")
        self.assertEqual(c_adm, 200)
        self.assertEqual(p_adm["profile"]["effectiveRole"], "admin")
        self.assertEqual(len(p_adm["profile"]["allowedModules"]), 7)

        c_op, p_op = operator.request("GET", "/api/admin/permissions")
        self.assertEqual(c_op, 200)
        self.assertEqual(p_op["profile"]["effectiveRole"], "operator")
        self.assertEqual(p_op["profile"]["allowedModules"], ["dashboard", "users", "works", "governance", "settings"])

        c_rev, p_rev = reviewer.request("GET", "/api/admin/permissions")
        self.assertEqual(c_rev, 200)
        self.assertEqual(p_rev["profile"]["effectiveRole"], "operator")
        self.assertEqual(p_rev["profile"]["allowedModules"], ["dashboard", "users", "works", "governance", "settings"])

        c_mod, p_mod = board_mod.request("GET", "/api/admin/permissions")
        self.assertEqual(c_mod, 200)
        self.assertEqual(p_mod["profile"]["effectiveRole"], "moderator")
        self.assertEqual(p_mod["profile"]["allowedModules"], ["mod_overview", "mod_topics", "mod_replies", "mod_reports"])
        self.assertIn("assets", p_mod["profile"]["moderatedBoards"])

        c_usr, _ = creator.request("GET", "/api/admin/permissions")
        self.assertEqual(c_usr, 403)

        # 2. Strict Role API Boundaries:
        # Operator CAN manage announcement & redeem codes, CANNOT access gateway, audit-logs, or economy settings
        c_op_ann, _ = operator.request(
            "POST",
            "/api/admin/settings",
            {"section": "announcement", "values": {"enabled": True, "badge": "运营季", "text": "春季共创激励上线"}},
        )
        self.assertEqual(c_op_ann, 200)
        c_op_rc, _ = operator.request("POST", "/api/admin/redeem-codes", {"code": "OPS2026", "credits": 25, "maxUses": 50})
        self.assertEqual(c_op_rc, 200)
        for denied_method, denied_path, denied_body in (
            ("GET", "/api/admin/gateway", None),
            ("GET", "/api/admin/audit-logs", None),
            ("POST", "/api/admin/settings", {"section": "economy", "values": {"daily_checkin_credits": 8}}),
            ("POST", "/api/admin/users/create", {"username": "ops_illegal_new"}),
        ):
            st_code, _ = operator.request(denied_method, denied_path, denied_body)
            self.assertEqual(st_code, 403, f"Operator must be blocked from {denied_path}")

        # Board Moderator CAN view moderator-overview (strictly 'assets') & moderate 'assets' topics,
        # CANNOT view global users/works or moderate 'tuning' topics!
        c_mc, mc_data = board_mod.request("GET", "/api/admin/moderator-overview")
        self.assertEqual(c_mc, 200)
        self.assertEqual([b["id"] for b in mc_data["allowedBoards"]], ["assets"])
        self.assertTrue(all(t["category"] == "assets" for t in mc_data["topics"]))
        assets_tid = mc_data["topics"][0]["id"]

        c_mod_ok, _ = board_mod.request(
            "POST",
            "/api/forum/moderate",
            {"topicId": assets_tid, "op": "feature", "reason": "本版版主加精"},
        )
        self.assertEqual(c_mod_ok, 200)

        _, adm_topics = admin.request("GET", "/api/admin/topics")
        tuning_tid = next(t["id"] for t in adm_topics["items"] if t["category"] == "tuning")
        c_mod_cross, _ = board_mod.request(
            "POST",
            "/api/forum/moderate",
            {"topicId": tuning_tid, "op": "pin", "reason": "越权置顶其他板块"},
        )
        self.assertEqual(c_mod_cross, 403)
        c_mod_users, _ = board_mod.request("GET", "/api/admin/users")
        self.assertEqual(c_mod_users, 403)

        # 3. Full User Lifecycle Management (Admin Create -> Appoint/Revoke Moderator -> Reset Password -> Self Profile -> Delete)
        c_create, created = admin.request(
            "POST",
            "/api/admin/users/create",
            {
                "username": "mod_candidate_xu",
                "displayName": "许版主",
                "password": "initPass123",
                "role": "user",
                "initialCredits": 45,
                "moderatorBoard": "tools",
                "moderatorTitle": "工具流版主",
            },
        )
        self.assertEqual(c_create, 200, created)
        new_uid = created["userId"]

        xu_cli = self.client("mod_candidate_xu", password="initPass123")
        c_xu_perm, xu_perm = xu_cli.request("GET", "/api/admin/permissions")
        self.assertEqual(c_xu_perm, 200)
        self.assertEqual(xu_perm["profile"]["effectiveRole"], "moderator")
        self.assertIn("tools", xu_perm["profile"]["moderatedBoards"])

        # Self-service profile update
        c_prof, _ = xu_cli.request("POST", "/api/auth/profile", {"displayName": "许版主·已改名", "bio": "热爱 ComfyUI 与手绘线稿"})
        self.assertEqual(c_prof, 200)

        # Super-admin resets password & revokes moderator, then deletes test account
        c_upd, _ = admin.request("POST", f"/api/admin/users/{new_uid}/update", {"newPassword": "resetPass789"})
        self.assertEqual(c_upd, 200)
        xu_relogin = self.client("mod_candidate_xu", password="resetPass789")
        _, b_xu = xu_relogin.request("GET", "/api/boot")
        self.assertEqual(b_xu["user"]["displayName"], "许版主·已改名")

        c_reappoint, _ = admin.request(
            "POST",
            "/api/admin/forum-moderators",
            {"username": "mod_candidate_xu", "category": "tools", "title": "资深工具版主"},
        )
        self.assertEqual(c_reappoint, 200)
        c_rev_mod, _ = admin.request("POST", "/api/admin/forum-moderators/revoke", {"username": "mod_candidate_xu", "category": "tools"})
        self.assertEqual(c_rev_mod, 200)
        c_del, _ = admin.request("POST", f"/api/admin/users/{new_uid}/delete", {"reason": "自动化测试清理账号"})
        self.assertEqual(c_del, 200)

        # 4. Standalone Rich-Text + Multi-Image Forum Post (/api/forum/topics)
        tiny_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
        c_post, post_res = creator.request(
            "POST",
            "/api/forum/topics",
            {
                "category": "experience",
                "title": "独立页面发帖测试：多图实测 FA-001 暖纸肌理对比",
                "summary": "正文支持段落排版与多张图文说明，无需弹窗即可沉浸式发帖。",
                "images": [
                    {"url": tiny_png, "tag": "本地直传实测图 P1"},
                    {"url": "/images/poster-demo-autumn-equinox.webp", "tag": "对照样张 P2"},
                ],
                "styles": ["FA-001"],
                "layout": "SC-021",
            },
        )
        self.assertEqual(c_post, 200, post_res)
        _, boot_after_post = creator.request("GET", "/api/boot")
        posted_topic = next(t for t in boot_after_post["topics"] if t["id"] == post_res["topicId"])
        self.assertEqual(len(posted_topic["images"]), 2)
        self.assertTrue(str(posted_topic["images"][0]["url"]).startswith("/uploads/"))

        # 5. Unified Comments, Likes, and Favorites on Styles ('FA-001'), Layouts ('SC-021'), and Works ('work_101')
        for target_type, target_id, col_bucket in (
            ("style", "FA-001", "styles"),
            ("layout", "SC-021", "layouts"),
            ("work", "work_101", "works"),
        ):
            c_lk, lk_res = creator.request("POST", "/api/interactions/like", {"targetType": target_type, "targetId": target_id})
            self.assertEqual(c_lk, 200, lk_res)
            self.assertIn("liked", lk_res)

            c_fav, fav_res = creator.request("POST", "/api/collections/toggle", {"bucket": col_bucket, "id": target_id, "title": target_id})
            self.assertEqual(c_fav, 200, fav_res)

        c_scmt, scmt_res = creator.request("POST", "/api/assets/FA-001/comments", {"kind": "style", "text": "FA-001 线条呼吸感极好！"})
        self.assertEqual(c_scmt, 200, scmt_res)
        c_lcmt, lcmt_res = creator.request("POST", "/api/assets/SC-021/comments", {"kind": "layout", "text": "SC-021 做节气对比海报非常稳！"})
        self.assertEqual(c_lcmt, 200, lcmt_res)
        c_wcmt, wcmt_res = creator.request("POST", "/api/works/work_101/comments", {"text": "作品配色太舒服了！"})
        self.assertEqual(c_wcmt, 200, wcmt_res)

        # Verify asset comments appear in /api/boot AND in /api/admin/comments governance queue
        _, boot_social = creator.request("GET", "/api/boot")
        self.assertTrue(any("呼吸感极好" in c["text"] for c in boot_social["assetComments"].get("FA-001", [])))
        self.assertTrue(any("节气对比海报" in c["text"] for c in boot_social["assetComments"].get("SC-021", [])))

        _, adm_cmts = reviewer.request("GET", f"/api/admin/comments?q={urllib.parse.quote('呼吸感极好')}")
        self.assertEqual(len(adm_cmts["items"]), 1)
        self.assertEqual(adm_cmts["items"][0]["commentType"], "asset_comment")

    def test_14_front_stage_delete_and_role_permissions(self):
        """Test front-stage granular deletion & moderation permissions:
        - Author can delete own work and own topic.
        - Normal user cannot delete other users' works or topics (403).
        - Board moderator can delete/moderate topics in their board ('assets'), blocked in other boards ('tuning').
        - Operator can moderate & delete community content across boards, but cannot delete admin's content.
        - Super-admin has full rights.
        """
        normal = self.client("su_editorial")
        board_mod = self.client("momo_design")
        operator = self.client("ops_lin")
        admin = self.client("yang0")

        # 1. Normal user creates a work
        c_pw, pw_res = normal.request(
            "POST",
            "/api/works",
            {
                "title": "普通创作者待删除作品测试",
                "images": ["/images/poster-demo-autumn-equinox.webp"],
                "styles": ["FA-001"],
                "notes": "普通创作者待删除作品测试的完整创作说明",
                "prompt": "待删除作品提示词",
            },
        )
        self.assertEqual(c_pw, 200)
        self.collect(pw_res)
        norm_wid = pw_res["workId"]

        # Board moderator (not author, not operator) tries to delete it -> 403
        c_del_mod_work, _ = board_mod.request("POST", f"/api/works/{norm_wid}/delete", {})
        self.assertEqual(c_del_mod_work, 403, "Board moderator cannot delete works outside operations")

        # Author deletes own work -> 200
        c_del_own, _ = normal.request("POST", f"/api/works/{norm_wid}/delete", {})
        self.assertEqual(c_del_own, 200)

        # 2. Forum topic delete permissions by board
        # Normal user posts in 'tuning'
        c_top_tun, top_tun_res = normal.request(
            "POST",
            "/api/forum/topics",
            {
                "category": "tuning",
                "title": "调优板块普通用户帖",
                "body": "这是普通用户发在调优板块的帖子内容",
            },
        )
        self.assertEqual(c_top_tun, 200)
        tun_tid = top_tun_res["topicId"]

        # Board moderator (assets only) tries to delete topic in tuning -> 403
        c_mod_tun, _ = board_mod.request("POST", f"/api/topics/{tun_tid}/moderate", {"action": "delete"})
        self.assertEqual(c_mod_tun, 403, "Assets moderator cannot delete topic in tuning board")

        # Normal user posts in 'assets'
        c_top_ast, top_ast_res = normal.request(
            "POST",
            "/api/forum/topics",
            {
                "category": "assets",
                "title": "资产板块讨论帖",
                "body": "这是普通用户发在资产板块的帖子内容",
            },
        )
        self.assertEqual(c_top_ast, 200)
        ast_tid = top_ast_res["topicId"]

        # Board moderator CAN delete topic in assets board -> 200
        c_mod_ast, _ = board_mod.request("POST", f"/api/topics/{ast_tid}/moderate", {"action": "delete"})
        self.assertEqual(c_mod_ast, 200)

        # 3. Operator can delete across boards, but cannot delete admin's post
        # Admin posts in tuning
        c_adm_top, adm_top_res = admin.request(
            "POST",
            "/api/forum/topics",
            {
                "category": "tuning",
                "title": "超管发布的调优置顶规范",
                "body": "超级管理员权威内容",
            },
        )
        self.assertEqual(c_adm_top, 200)
        adm_tid = adm_top_res["topicId"]

        # Operator tries to delete admin's topic -> 403
        c_op_del_adm, err_op = operator.request("POST", f"/api/topics/{adm_tid}/moderate", {"action": "delete"})
        self.assertEqual(c_op_del_adm, 403)
        self.assertIn("超级管理员", err_op.get("error", ""))

        # Super-admin deletes own topic -> 200
        c_adm_del_adm, _ = admin.request("POST", f"/api/topics/{adm_tid}/moderate", {"action": "delete"})
        self.assertEqual(c_adm_del_adm, 200)


if __name__ == "__main__":
    unittest.main()
