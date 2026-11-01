"""Every image prompt must come from the hand-drawn style Skill.

The founder's rule: no path may send a picture request straight to the image
model from a style label — the Skill resolves the style's traits and the
layout's composition rules first.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from backend import skill_paths, skill_prompt
from backend.services import _compose_skill_prompt

REPO = "https://github.com/yang0/handraw-style"


class SkillPromptTests(unittest.TestCase):
    def test_the_skill_package_is_reachable(self):
        if not skill_prompt.skill_available():
            self.skipTest("hand-drawn style Skill checkout not present")
        self.assertGreater(len(skill_prompt._styles()), 100, "the style catalogue should load")
        self.assertGreater(len(skill_prompt._layouts()), 10, "the layout catalogue should load")
        self.assertEqual(skill_paths.SKILL_REPO, REPO, "the Skill's upstream repo is recorded")

    def test_a_style_and_layout_produce_a_composed_prompt(self):
        if not skill_prompt.skill_available():
            self.skipTest("hand-drawn style Skill checkout not present")
        composed = skill_prompt.compose_prompt("FA-013", "SC-021", "", "a boy holding a surfboard")
        self.assertTrue(composed["prompt"], "the Skill must return a prompt for a real style and layout")
        # Assert on the facts the Skill resolved, not on the model's wording: the
        # generated text varies between runs and asserting on it made this test
        # flake.
        self.assertEqual(composed["facts"]["style"]["id"], "FA-013")
        self.assertEqual(composed["facts"]["layout"]["id"], "SC-021")
        self.assertTrue(composed["facts"]["style"]["traits"], "the style's traits should resolve")
        self.assertTrue(composed["facts"]["layout"]["rules"], "the layout's rules should resolve")
        self.assertIn(composed["source"], ("model", "template"))

    def test_the_layout_rules_reach_the_prompt(self):
        # The point of the Skill is that the layout constrains the picture; a
        # prompt that only names the style has not used it.
        if not skill_prompt.skill_available():
            self.skipTest("hand-drawn style Skill checkout not present")
        composed = skill_prompt.compose_prompt("FA-013", "SC-021", "", "a boy holding a surfboard")
        rules = composed["facts"]["layout"]["rules"]
        self.assertTrue(len(rules) > 100, "SC-021 should carry its own composition rules")
        # The template path is deterministic, so it can be checked exactly.
        template = skill_prompt._template(composed["facts"])
        self.assertIn("SC-021", template)
        self.assertGreater(len(template), len(composed["facts"]["style"]["traits"]))

    def test_strip_bilingual_definition(self):
        sample = (
            "<!-- zh -->\n"
            "漫画分镜。排版：规则网格，所有面板大小接近。\n\n"
            "<!-- en -->\n"
            "Comic storyboard. Layout: Regular Grid.\n"
        )
        cleaned = skill_prompt.strip_bilingual_definition(sample)
        self.assertEqual(cleaned, "漫画分镜。排版：规则网格，所有面板大小接近。")
        self.assertNotIn("<!-- zh -->", cleaned)
        self.assertNotIn("<!-- en -->", cleaned)
        self.assertNotIn("Comic storyboard", cleaned)

        # Variations of spacing and case
        self.assertEqual(skill_prompt.strip_bilingual_definition("<!--zh-->测试<!--en-->test"), "测试")
        self.assertEqual(skill_prompt.strip_bilingual_definition("<!--  ZH  -->内容<!--  EN  -->content"), "内容")
        self.assertEqual(skill_prompt.strip_bilingual_definition("无标签中文"), "无标签中文")
        self.assertEqual(skill_prompt.strip_bilingual_definition(""), "")
        self.assertEqual(skill_prompt.strip_bilingual_definition(None), "")

    def test_layout_rules_contain_no_english_or_tags(self):
        if not skill_prompt.skill_available():
            self.skipTest("hand-drawn style Skill checkout not present")
        for code in ("SB-001", "SC-001", "SC-021", "EC-001", "IG-001"):
            rules = skill_prompt._layout_rules(code)
            self.assertTrue(rules, f"Rules for {code} should not be empty")
            self.assertNotIn("<!-- en -->", rules)
            self.assertNotIn("<!--en-->", rules)
            self.assertNotIn("<!-- zh -->", rules)
            self.assertNotIn("<!--zh-->", rules)

    def test_catalog_and_editorial_layouts_are_chinese_only(self):
        import json
        catalog_path = Path(__file__).resolve().parent.parent / "plugin" / "content" / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        layouts = [r for r in catalog["resources"] if r.get("kind") == "layout"]
        self.assertEqual(len(layouts), 168, "Must contain exactly 168 layout definitions")
        for item in layouts:
            defn = item.get("definition", "")
            self.assertTrue(defn, f"Layout {item['id']} definition must not be empty")
            self.assertNotIn("<!-- en -->", defn)
            self.assertNotIn("<!--en-->", defn)
            self.assertNotIn("<!-- zh -->", defn)
            self.assertNotIn("<!--zh-->", defn)

        editorial_path = Path(__file__).resolve().parent.parent / "plugin" / "content" / "editorial.json"
        editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
        for item in editorial.get("featured_layouts", []):
            defn = item.get("definition", "")
            self.assertTrue(defn, f"Featured layout {item['id']} definition must not be empty")
            self.assertNotIn("<!-- en -->", defn)
            self.assertNotIn("<!--en-->", defn)
            self.assertNotIn("<!-- zh -->", defn)
            self.assertNotIn("<!--zh-->", defn)

    def test_without_parameters_the_helper_returns_nothing(self):
        # An empty request must fall back, not invent a prompt.
        self.assertEqual(_compose_skill_prompt("", "", ""), "")

    def test_unknown_style_falls_back_instead_of_raising(self):
        self.assertEqual(_compose_skill_prompt("ZZ-999", "", "theme"), "")

    def test_no_hard_coded_credentials_in_the_parser(self):
        source = (Path(__file__).resolve().parent.parent / "backend" / "document_parser.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("sk-", source, "the parser must not carry a literal API key")

    def test_compose_prompt_executed_outside_database_write_transaction(self):
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        from backend.server import init_database
        from backend.services import prepare_cloud_generation, register_user

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            db = init_database(db_path)
            user, _ = register_user(db, "test_prompt_user", "password123")

            call_checked = False

            def mocked_compose(style_code: str, layout_code: str, theme: str) -> str:
                nonlocal call_checked
                call_checked = True
                conn = db.get_conn()
                self.assertFalse(conn.in_transaction, "Database connection must not be in an open write transaction")
                test_conn = db._connect()
                try:
                    test_conn.execute("BEGIN IMMEDIATE;")
                    test_conn.execute("COMMIT;")
                finally:
                    test_conn.close()
                return "Skill Prompt Mocked: Hand-drawn masterpiece"

            with patch("backend.services._compose_skill_prompt", side_effect=mocked_compose):
                res = prepare_cloud_generation(
                    db,
                    user,
                    {"prompt": "my drawing", "style1": "FA-001", "requestId": "req-tx-test-1"},
                )

            self.assertTrue(call_checked, "_compose_skill_prompt should have been invoked")
            self.assertEqual(res["finalPrompt"], "Skill Prompt Mocked: Hand-drawn masterpiece")

            saved_row = db.get_conn().execute(
                "SELECT prompt FROM studio_generations WHERE id = ?", (res["genId"],)
            ).fetchone()
            self.assertEqual(saved_row["prompt"], "Skill Prompt Mocked: Hand-drawn masterpiece")

            call_checked_retry = False

            def mocked_compose_retry(style_code: str, layout_code: str, theme: str) -> str:
                nonlocal call_checked_retry
                call_checked_retry = True
                return "Should not be called"

            with patch("backend.services._compose_skill_prompt", side_effect=mocked_compose_retry):
                res_retry = prepare_cloud_generation(
                    db,
                    user,
                    {"prompt": "my drawing", "style1": "FA-001", "requestId": "req-tx-test-1"},
                )

            self.assertFalse(call_checked_retry, "Retry with existing requestId must skip model invocation")
            self.assertTrue(res_retry["idempotent"])
            self.assertEqual(res_retry["genId"], res["genId"])

            db.close_thread_conn()
            db.close()

    def test_in_progress_task_rejects_without_calling_compose(self):
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        from backend.server import init_database
        from backend.services import ServiceError, prepare_cloud_generation, register_user

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_inflight.db"
            db = init_database(db_path)
            user, _ = register_user(db, "inflight_user", "password123")

            res1 = prepare_cloud_generation(
                db,
                user,
                {"prompt": "first task", "style1": "FA-001", "requestId": "req-inflight-1"},
            )
            self.assertEqual(res1["status"], "running")

            compose_call_count = 0

            def mocked_compose(style_code: str, layout_code: str, theme: str) -> str:
                nonlocal compose_call_count
                compose_call_count += 1
                return "Should never be called"

            with patch("backend.services._compose_skill_prompt", side_effect=mocked_compose):
                with self.assertRaises(ServiceError) as ctx:
                    prepare_cloud_generation(
                        db,
                        user,
                        {"prompt": "second task", "style1": "FA-001", "requestId": "req-inflight-2"},
                    )

            self.assertEqual(ctx.exception.status, 429)
            self.assertEqual(ctx.exception.code, "generation_in_progress")
            self.assertEqual(compose_call_count, 0, "compose must be called 0 times when admission check fails")

            db.close_thread_conn()
            db.close()

    def test_concurrent_same_request_id_calls_compose_once(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        from backend.server import init_database
        from backend.services import prepare_cloud_generation, register_user

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_concurrent.db"
            db = init_database(db_path)
            user, _ = register_user(db, "concurrent_user", "password123")

            compose_call_count = 0

            def mocked_compose(style_code: str, layout_code: str, theme: str) -> str:
                nonlocal compose_call_count
                compose_call_count += 1
                time.sleep(0.08)
                return "Skill Prompt Concurrent Success"

            results = []
            errors = []

            def worker():
                try:
                    res = prepare_cloud_generation(
                        db,
                        user,
                        {"prompt": "draw race", "style1": "FA-001", "requestId": "req-concurrent-same"},
                    )
                    results.append(res)
                except Exception as exc:
                    errors.append(exc)
                finally:
                    db.close_thread_conn()

            with patch("backend.services._compose_skill_prompt", side_effect=mocked_compose):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    f1 = executor.submit(worker)
                    f2 = executor.submit(worker)
                    f1.result()
                    f2.result()

            self.assertEqual(errors, [], f"No errors expected, got: {errors}")
            self.assertEqual(len(results), 2)
            self.assertEqual(compose_call_count, 1, "compose must be called exactly 1 time under concurrent same requestId")

            rows = db.get_conn().execute(
                "SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ?",
                (int(user["id"]), "req-concurrent-same"),
            ).fetchall()
            self.assertEqual(len(rows), 1, "Only 1 studio_generations row should be created")

            w = db.get_conn().execute("SELECT free_quota_used FROM wallets WHERE user_id = ?", (int(user["id"]),)).fetchone()
            self.assertEqual(w["free_quota_used"], 1, "Free quota must only be debited 1 time")

            db.close_thread_conn()
            db.close()

    def test_retry_during_compose_returns_202_and_does_not_submit_to_gateway(self):
        import os
        import json
        import threading
        import urllib.request
        import urllib.error
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from http.server import ThreadingHTTPServer
        from backend.server import init_database, HandrawRequestHandler
        from backend.services import register_user

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_retry_block.db"
            uploads_dir = Path(temp_dir) / "uploads"
            generated_dir = Path(temp_dir) / "generated"
            uploads_dir.mkdir()
            generated_dir.mkdir()

            with patch.dict(os.environ, {
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_DB_PATH": str(db_path),
                "HANDRAW_UPLOADS_DIR": str(uploads_dir),
                "HANDRAW_GENERATED_DIR": str(generated_dir),
            }):
                db = init_database(db_path)
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
                httpd.channel_role = "main"
                httpd.db = db
                port = httpd.server_address[1]
                base_url = f"http://127.0.0.1:{port}"
                server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                server_thread.start()

                try:
                    _, token = register_user(db, "tester_retry_user", "password123")

                    compose_started = threading.Event()
                    compose_proceed = threading.Event()
                    gw_calls = []

                    def mocked_compose(style, layout, theme):
                        compose_started.set()
                        compose_proceed.wait(timeout=5)
                        return "Composed Skill Version: Beautiful Art"

                    def mocked_gw(path, payload=None, timeout=30):
                        gw_calls.append(payload)
                        return {"id": "gw_task_123", "status": "queued"}

                    def post(body):
                        req = urllib.request.Request(
                            f"{base_url}/api/studio/generate",
                            data=json.dumps(body).encode("utf-8"),
                            headers={
                                "Content-Type": "application/json",
                                "Accept": "application/json",
                                "Authorization": f"Bearer {token}",
                            },
                            method="POST",
                        )
                        try:
                            with urllib.request.urlopen(req, timeout=15) as resp:
                                return resp.status, json.loads(resp.read().decode("utf-8"))
                        except urllib.error.HTTPError as err:
                            return err.code, json.loads(err.read().decode("utf-8"))

                    with patch("backend.services._compose_skill_prompt", side_effect=mocked_compose), \
                         patch("backend.server.load_image_service_config", return_value={"base_url": "http://mock-gw", "key": "k"}), \
                         patch("backend.server.gateway_request", side_effect=mocked_gw):

                        req1_res = {}
                        def req1_worker():
                            code, data = post({
                                "prompt": "draw dragon",
                                "style1": "FA-001",
                                "requestId": "req-block-test-1",
                            })
                            req1_res["code"] = code
                            req1_res["data"] = data

                        t1 = threading.Thread(target=req1_worker)
                        t1.start()

                        self.assertTrue(compose_started.wait(timeout=5), "Compose should have started")

                        # Retry while compose is blocked
                        retry_code, retry_data = post({
                            "prompt": "draw dragon",
                            "style1": "FA-001",
                            "requestId": "req-block-test-1",
                        })

                        self.assertEqual(retry_code, 202, f"Retry during compose must return 202, got {retry_code}: {retry_data}")
                        self.assertEqual(retry_data.get("status"), "running")
                        self.assertEqual(len(gw_calls), 0, "Gateway must NOT be called by retry while compose is in-progress")

                        compose_proceed.set()
                        t1.join(timeout=5)

                        self.assertEqual(req1_res.get("code"), 200)
                        self.assertEqual(len(gw_calls), 1, "Gateway should have been called once after compose unblocks")
                        self.assertIn("Composed Skill Version: Beautiful Art", gw_calls[0]["prompt"])

                        saved_row = db.get_conn().execute(
                            "SELECT prompt, prompt_ready FROM studio_generations WHERE request_id = 'req-block-test-1'"
                        ).fetchone()
                        self.assertIn("Composed Skill Version: Beautiful Art", saved_row["prompt"])
                        self.assertEqual(saved_row["prompt_ready"], 1)

                        w = db.get_conn().execute(
                            "SELECT free_quota_used FROM wallets WHERE user_id = (SELECT id FROM users WHERE username = 'tester_retry_user')"
                        ).fetchone()
                        self.assertEqual(w["free_quota_used"], 1, "Quota should only be debited once")

                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    server_thread.join(timeout=5)
                    db.close()

    def test_compose_exception_fallback_to_initial_prompt(self):
        import os
        import json
        import threading
        import urllib.request
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from http.server import ThreadingHTTPServer
        from backend.server import init_database, HandrawRequestHandler
        from backend.services import register_user

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_g2_exception.db"
            uploads_dir = Path(temp_dir) / "uploads"
            generated_dir = Path(temp_dir) / "generated"
            uploads_dir.mkdir()
            generated_dir.mkdir()

            with patch.dict(os.environ, {
                "HANDRAW_DEMO_MODE": "1",
                "HANDRAW_DB_PATH": str(db_path),
                "HANDRAW_UPLOADS_DIR": str(uploads_dir),
                "HANDRAW_GENERATED_DIR": str(generated_dir),
            }):
                db = init_database(db_path)
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
                httpd.channel_role = "main"
                httpd.db = db
                port = httpd.server_address[1]
                base_url = f"http://127.0.0.1:{port}"
                server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                server_thread.start()

                try:
                    _, token = register_user(db, "tester_g2_user", "password123")
                    gw_calls = []

                    def mocked_compose_err(style, layout, theme):
                        raise RuntimeError("External AI service timeout")

                    def mocked_gw(path, payload=None, timeout=30):
                        gw_calls.append(payload)
                        return {"id": "gw_task_g2", "status": "queued"}

                    req = urllib.request.Request(
                        f"{base_url}/api/studio/generate",
                        data=json.dumps({
                            "prompt": "fallback prompt test",
                            "style1": "FA-001",
                            "requestId": "req-g2-fallback-1",
                        }).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Authorization": f"Bearer {token}",
                        },
                        method="POST",
                    )

                    with patch("backend.services._compose_skill_prompt", side_effect=mocked_compose_err), \
                         patch("backend.server.load_image_service_config", return_value={"base_url": "http://mock-gw", "key": "k"}), \
                         patch("backend.server.gateway_request", side_effect=mocked_gw):
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            code = resp.status
                            data = json.loads(resp.read().decode("utf-8"))

                    self.assertEqual(code, 200, f"Exception in compose must not return 500, got {code}: {data}")
                    self.assertEqual(len(gw_calls), 1)
                    self.assertIn("fallback prompt test", gw_calls[0]["prompt"])

                    saved_row = db.get_conn().execute(
                        "SELECT prompt, prompt_ready FROM studio_generations WHERE request_id = 'req-g2-fallback-1'"
                    ).fetchone()
                    self.assertEqual(saved_row["prompt_ready"], 1)
                    self.assertIn("fallback prompt test", saved_row["prompt"])

                    w = db.get_conn().execute(
                        "SELECT free_quota_used FROM wallets WHERE user_id = (SELECT id FROM users WHERE username = 'tester_g2_user')"
                    ).fetchone()
                    self.assertEqual(w["free_quota_used"], 1, "Quota should only be debited once")

                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    server_thread.join(timeout=5)
                    db.close()

    def test_requests_not_needing_compose_set_prompt_ready_1(self):
        from tempfile import TemporaryDirectory
        from backend.server import init_database
        from backend.services import register_user, prepare_cloud_generation

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_prompt_ready_1.db"
            db = init_database(db_path)
            u1, _ = register_user(db, "ready_user_1", "password123")
            u2, _ = register_user(db, "ready_user_2", "password123")

            # 1. promptFromSkill = True
            res1 = prepare_cloud_generation(db, u1, {
                "prompt": "already composed prompt",
                "promptFromSkill": True,
                "style1": "FA-001",
                "requestId": "req-ready-1",
            })
            row1 = db.get_conn().execute("SELECT prompt_ready FROM studio_generations WHERE id = ?", (res1["genId"],)).fetchone()
            self.assertEqual(row1["prompt_ready"], 1, "promptFromSkill=True must insert with prompt_ready=1")

            # 2. No style or layout
            res2 = prepare_cloud_generation(db, u2, {
                "prompt": "plain raw prompt",
                "promptFromSkill": False,
                "style1": "",
                "layout": "",
                "requestId": "req-ready-2",
            })
            row2 = db.get_conn().execute("SELECT prompt_ready FROM studio_generations WHERE id = ?", (res2["genId"],)).fetchone()
            self.assertEqual(row2["prompt_ready"], 1, "No style or layout must insert with prompt_ready=1")

            db.close_thread_conn()
            db.close()

    def test_reconcile_once_cleans_up_stale_unready_prompts(self):
        from datetime import datetime, timezone, timedelta
        from tempfile import TemporaryDirectory
        from backend.server import init_database, GenerationReconciler

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_reconcile_stale.db"
            db = init_database(db_path)

            now_dt = datetime.now(timezone.utc)
            old_time = (now_dt - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%SZ")
            recent_time = (now_dt - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

            with db.transaction() as tx:
                tx.execute(
                    """
                    INSERT INTO studio_generations (
                        id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                        prompt, markdown, items_json, engine, cost_type, credits_spent, task_id,
                        status, error_msg, request_id, reservation_date, created_at, prompt_ready
                    ) VALUES ('gen_stale_11m', 1, 'u', 't', '3:4', 'l', 'single', 'r', 'p1', '', '[]', 'live', 'free_quota', 0, '', 'running', '', 'req_stale', '2026-10-31', ?, 0)
                    """,
                    (old_time,),
                )
                tx.execute(
                    """
                    INSERT INTO studio_generations (
                        id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                        prompt, markdown, items_json, engine, cost_type, credits_spent, task_id,
                        status, error_msg, request_id, reservation_date, created_at, prompt_ready
                    ) VALUES ('gen_recent_1m', 1, 'u', 't', '3:4', 'l', 'single', 'r', 'p2', '', '[]', 'live', 'free_quota', 0, '', 'running', '', 'req_recent', '2026-10-31', ?, 0)
                    """,
                    (recent_time,),
                )

            reconciler = GenerationReconciler(db)
            reconciler.reconcile_once()

            r_old = db.get_conn().execute("SELECT prompt_ready FROM studio_generations WHERE id = 'gen_stale_11m'").fetchone()
            r_recent = db.get_conn().execute("SELECT prompt_ready FROM studio_generations WHERE id = 'gen_recent_1m'").fetchone()

            self.assertEqual(r_old["prompt_ready"], 1, "Generation older than 10 minutes must have prompt_ready cleaned up to 1")
            self.assertEqual(r_recent["prompt_ready"], 0, "Recent generation must keep prompt_ready=0")

            db.close_thread_conn()
            db.close()


if __name__ == "__main__":
    unittest.main()
