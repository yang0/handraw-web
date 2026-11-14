"""Integration tests for standalone Meilisearch full-text search, outbox worker, and atomic rebuild."""
from __future__ import annotations

import http.client
import json
import os
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from backend import forum_boards as B
from backend import search_service as SS
from backend import services as S
from backend.curation import publish_work_direct
from backend.search_engine import SearchEngine, index_name
from backend.search_worker import SearchWorker
from backend.server import create_channel_server
from tests.postgres_support import open_isolated_postgres


def _terms(text: str, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    clean = str(text or "").strip().lower()
    if not clean:
        return []
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*|[\u4e00-\u9fff]+", clean)
    expanded: list[str] = []
    for tok in tokens:
        expanded.append(tok)
        if re.fullmatch(r"[\u4e00-\u9fff]+", tok) and len(tok) > 2:
            # Split long CJK phrases into bigrams + full token for Chinese segmentation simulation.
            for i in range(len(tok) - 1):
                expanded.append(tok[i : i + 2])
    if synonyms:
        for base, alts in synonyms.items():
            if base.lower() in expanded or base.lower() in clean:
                for alt in alts:
                    expanded.append(alt.lower())
    return list(dict.fromkeys(expanded))


def _highlight(text: str, query_tokens: list[str], pre: str, post: str) -> str:
    raw = str(text or "")
    for tok in sorted({t for t in query_tokens if t}, key=len, reverse=True):
        pattern = re.compile(re.escape(tok), re.IGNORECASE)
        if pattern.search(raw):
            return pattern.sub(lambda m: f"{pre}{m.group(0)}{post}", raw)
    return raw


class FakeMeilisearchState:
    def __init__(self, read_key: str, write_key: str):
        self.read_key = read_key
        self.write_key = write_key
        self.lock = threading.Lock()
        self.indexes: dict[str, dict] = {}
        self.tasks: dict[int, dict] = {}
        self.next_task_uid = 1
        self.down = False
        self.fail_next_writes = 0
        self.fail_next_task_code = ""
        self.fail_swap = False

    def new_task(self, *, fail_code: str = "") -> dict:
        uid = self.next_task_uid
        self.next_task_uid += 1
        code = fail_code or self.fail_next_task_code
        if not fail_code and self.fail_next_task_code:
            self.fail_next_task_code = ""
        if code:
            task = {"taskUid": uid, "status": "failed", "error": {"code": code}}
        else:
            task = {"taskUid": uid, "status": "succeeded"}
        self.tasks[uid] = task
        return {"taskUid": uid, "status": "enqueued"}

    def search_index(self, query: dict) -> list[dict]:
        uid = query["indexUid"]
        q = str(query.get("q") or "").strip()
        q_norm = re.sub(r"[^a-z0-9]+", "", q.lower())
        idx = self.indexes.get(uid)
        if not idx:
            return []
        settings = idx["settings"]
        attrs = settings.get("searchableAttributes") or ["code", "title", "aliases", "tags", "author", "body"]
        synonyms = settings.get("synonyms") or {}
        board_allow: set[str] | None = None
        flt = str(query.get("filter") or "")
        m = re.match(r"board\s+IN\s+(\[.*\])", flt)
        if m:
            board_allow = set(json.loads(m.group(1)))

        q_tokens = _terms(q)
        pre = query.get("highlightPreTag", "\ue000")
        post = query.get("highlightPostTag", "\ue001")
        sort_rules = list(query.get("sort") or [])

        best_by_root: dict[str, tuple[float, int, dict]] = {}
        for doc in idx["docs"].values():
            if board_allow is not None and doc.get("board") not in board_allow:
                continue
            field_texts = {a: str(doc.get(a) or "").lower() for a in attrs}
            all_text = " ".join(field_texts.values())
            expanded_all = all_text
            for k, alts in synonyms.items():
                if k.lower() in all_text:
                    expanded_all += " " + " ".join(a.lower() for a in alts)
            if q:
                # Match all query tokens across combined document + synonyms, or exact normalized code.
                code_match = bool(q_norm) and q_norm == re.sub(r"[^a-z0-9]+", "", field_texts.get("code", ""))
                alias_tokens = re.findall(r"[a-z0-9]+", field_texts.get("aliases", ""))
                exact_tok_match = q.lower() in expanded_all
                all_toks = bool(q_tokens) and all(tok in expanded_all for tok in q_tokens)
                syn_match = any(
                    alt.lower() in expanded_all
                    for tok in q_tokens
                    for alt in synonyms.get(tok, [])
                )
                if not (code_match or exact_tok_match or all_toks or syn_match or q.lower() in alias_tokens):
                    continue
            score = 0.0
            for weight_idx, attr in enumerate(attrs):
                txt = field_texts.get(attr, "")
                w = float(len(attrs) - weight_idx + 1) * 10.0
                if q and q.lower() in txt:
                    score += w * 2.0
                for tok in q_tokens:
                    if tok in txt:
                        score += w
                if attr == "aliases" and q.lower() in re.findall(r"[a-z0-9]+", txt):
                    score += w * 2.5
                if attr == "code" and q_norm and q_norm == re.sub(r"[^a-z0-9]+", "", txt):
                    score += 500.0
            root = str(doc.get("result_id") or doc["id"])
            published = int(doc.get("published") or 0)
            prev = best_by_root.get(root)
            sort_key = (published if sort_rules == ["published:desc"] else score, score, published)
            if prev is None or sort_key > prev[0]:
                hit = dict(doc)
                hl_tokens = list(q_tokens)
                for base, alts in synonyms.items():
                    if base.lower() in q.lower():
                        hl_tokens.extend(alts)
                hit["_formatted"] = {
                    "title": _highlight(doc.get("title", ""), hl_tokens, pre, post),
                    "body": _highlight(doc.get("body", "")[:240], hl_tokens, pre, post),
                }
                hit["_score"] = score
                best_by_root[root] = (sort_key, hit)

        ranked = [entry[1] for entry in best_by_root.values()]
        if sort_rules == ["published:desc"]:
            ranked.sort(key=lambda h: (-int(h.get("published") or 0), str(h.get("id") or "")))
        else:
            ranked.sort(key=lambda h: (-float(h.get("_score") or 0.0), -int(h.get("published") or 0), str(h.get("id") or "")))
        for item in ranked:
            item.pop("_score", None)
        return ranked


class FakeMeilisearchServer:
    def __init__(self):
        self.state = FakeMeilisearchState("test_read_key", "test_write_key")
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                pass

            def _send(self, code: int, payload: dict):
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth(self, *, write: bool) -> bool:
                hdr = self.headers.get("Authorization") or ""
                allowed = {f"Bearer {state.write_key}"}
                if not write:
                    allowed.add(f"Bearer {state.read_key}")
                if hdr not in allowed:
                    self._send(403, {"message": "invalid_api_key"})
                    return False
                return True

            def _body(self):
                length = int(self.headers.get("Content-Length") or "0")
                return json.loads(self.rfile.read(length).decode("utf-8")) if length else None

            def do_GET(self):
                if state.down:
                    self._send(503, {"status": "unavailable"})
                    return
                if self.path == "/health":
                    self._send(200, {"status": "available"})
                    return
                if not self._auth(write=False):
                    return
                with state.lock:
                    if self.path.startswith("/indexes?"):
                        results = [{"uid": k, "primaryKey": v["primaryKey"]} for k, v in state.indexes.items()]
                        self._send(200, {"results": results})
                        return
                    m_stats = re.fullmatch(r"/indexes/([^/]+)/stats", self.path)
                    if m_stats:
                        idx = state.indexes.get(m_stats.group(1))
                        if not idx:
                            self._send(404, {"code": "index_not_found"})
                            return
                        self._send(200, {"numberOfDocuments": len(idx["docs"])})
                        return
                    m_task = re.fullmatch(r"/tasks/(\d+)", self.path)
                    if m_task:
                        task = state.tasks.get(int(m_task.group(1)))
                        if not task:
                            self._send(404, {"code": "task_not_found"})
                            return
                        self._send(200, task)
                        return
                self._send(404, {"code": "not_found"})

            def do_POST(self):
                if state.down:
                    self._send(503, {"code": "unavailable"})
                    return
                if self.path == "/multi-search":
                    if not self._auth(write=False):
                        return
                    body = self._body() or {}
                    queries = body.get("queries") or []
                    with state.lock:
                        if "federation" in body:
                            fed = body["federation"]
                            off = int(fed.get("offset") or 0)
                            lim = int(fed.get("limit") or 20)
                            combined: list[dict] = []
                            for q in queries:
                                combined.extend(state.search_index(q))
                            combined.sort(key=lambda h: (0,))
                            # Preserve higher-priority field/query hits across federated results.
                            seen_ids = set()
                            deduped = []
                            for hit in combined:
                                if hit["id"] not in seen_ids:
                                    seen_ids.add(hit["id"])
                                    deduped.append(hit)
                            self._send(200, {"hits": deduped[off : off + lim]})
                        else:
                            results = []
                            for q in queries:
                                lim = int(q.get("limit") or 20)
                                off = int(q.get("offset") or 0)
                                hits = state.search_index(q)[off : off + lim]
                                results.append({"indexUid": q["indexUid"], "hits": hits})
                            self._send(200, {"results": results})
                    return

                if not self._auth(write=True):
                    return
                body = self._body()
                with state.lock:
                    if state.fail_next_writes > 0:
                        state.fail_next_writes -= 1
                        self._send(503, {"code": "simulated_write_error"})
                        return
                    if self.path == "/indexes":
                        uid = body["uid"]
                        if uid not in state.indexes:
                            state.indexes[uid] = {"primaryKey": body.get("primaryKey", "id"), "settings": {}, "docs": {}}
                        self._send(202, state.new_task())
                        return
                    m_docs = re.fullmatch(r"/indexes/([^/]+)/documents", self.path)
                    if m_docs:
                        uid = m_docs.group(1)
                        idx = state.indexes.get(uid)
                        if not idx:
                            self._send(404, {"code": "index_not_found"})
                            return
                        for doc in body or []:
                            idx["docs"][doc["id"]] = dict(doc)
                        self._send(202, state.new_task())
                        return
                    m_del = re.fullmatch(r"/indexes/([^/]+)/documents/delete", self.path)
                    if m_del:
                        uid = m_del.group(1)
                        idx = state.indexes.get(uid)
                        if not idx:
                            self._send(404, {"code": "index_not_found"})
                            return
                        flt = str((body or {}).get("filter") or "")
                        m_eq = re.match(r"result_id\s*=\s*(\".*\")", flt)
                        if m_eq:
                            root = json.loads(m_eq.group(1))
                            for did in [k for k, v in idx["docs"].items() if v.get("result_id") == root]:
                                idx["docs"].pop(did, None)
                        self._send(202, state.new_task())
                        return
                    if self.path == "/swap-indexes":
                        if state.fail_swap:
                            state.fail_swap = False
                            self._send(202, state.new_task(fail_code="simulated_swap_failed"))
                            return
                        for pair in body or []:
                            a, b = pair["indexes"]
                            idx_a = state.indexes.pop(a, {"primaryKey": "id", "settings": {}, "docs": {}})
                            idx_b = state.indexes.pop(b, {"primaryKey": "id", "settings": {}, "docs": {}})
                            state.indexes[a] = idx_b
                            state.indexes[b] = idx_a
                        self._send(202, state.new_task())
                        return
                self._send(404, {"code": "not_found"})

            def do_PATCH(self):
                if state.down:
                    self._send(503, {"code": "unavailable"})
                    return
                if not self._auth(write=True):
                    return
                m = re.fullmatch(r"/indexes/([^/]+)/settings", self.path)
                if m:
                    body = self._body() or {}
                    with state.lock:
                        idx = state.indexes.get(m.group(1))
                        if not idx:
                            self._send(404, {"code": "index_not_found"})
                            return
                        idx["settings"].update(body)
                        self._send(202, state.new_task())
                    return
                self._send(404, {"code": "not_found"})

            def do_DELETE(self):
                if state.down:
                    self._send(503, {"code": "unavailable"})
                    return
                if not self._auth(write=True):
                    return
                m = re.fullmatch(r"/indexes/([^/]+)", self.path)
                if m:
                    with state.lock:
                        state.indexes.pop(m.group(1), None)
                        self._send(202, state.new_task())
                    return
                self._send(404, {"code": "not_found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


class FulltextSearchTests(unittest.TestCase):
    IMG = "/images/individual/FA/FA-013.webp"

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.real_meili = os.environ.get("HANDRAW_TEST_REAL_MEILI") == "1"
        if self.real_meili:
            self.meili = None
            env_patch = {"HANDRAW_PRIVATE_STORAGE": str(self.root), "HANDRAW_DEMO_MODE": "0"}
        else:
            self.meili = FakeMeilisearchServer()
            self.addCleanup(self.meili.close)
            env_patch = {
                "HANDRAW_PRIVATE_STORAGE": str(self.root),
                "HANDRAW_DEMO_MODE": "0",
                "HANDRAW_SEARCH_URL": self.meili.url,
                "HANDRAW_SEARCH_KEY": "test_read_key",
                "HANDRAW_SEARCH_WRITE_KEY": "test_write_key",
                "HANDRAW_SEARCH_CURSOR_KEY": "cursor_secret_test_key",
            }
        self.enterContext(patch.dict(os.environ, env_patch))
        self.db = open_isolated_postgres(self)
        self.admin, self.admin_token = S.register_user(self.db, "search_admin", "SearchPass123!")
        self.member, self.member_token = S.register_user(self.db, "search_member", "SearchPass123!")
        self.outsider, self.outsider_token = S.register_user(self.db, "search_outsider", "SearchPass123!")
        self.db.get_conn().execute("UPDATE users SET role='admin' WHERE id=?", (self.admin["id"],))
        self.admin.update(role="admin", status="active")

        self.server = create_channel_server(0, "main", self.db, host="127.0.0.1", demo_mode=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.worker = SearchWorker(self.db)
        self.worker.initialize()
        # Drain initial queued per-channel rebuilds so indexes reflect baseline catalog + content.
        self._drain_worker()
        self.db.close_thread_conn()

    def _drain_worker(self, max_ticks: int = 12):
        for _ in range(max_ticks):
            self.worker.tick()
            row = self.db.get_conn().execute(
                "SELECT count(*) FROM search_jobs WHERE status IN ('queued','running','swapping')"
            ).fetchone()
            pending = self.db.get_conn().execute(
                "SELECT count(*) FROM search_events WHERE processed_at IS NULL"
            ).fetchone()
            if int(row[0]) == 0 and int(pending[0]) == 0:
                break

    def _http(self, method: str, path: str, *, token: str | None = None, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        raw = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        conn.request(method, path, raw, headers)
        resp = conn.getresponse()
        payload = resp.read()
        loc = resp.getheader("Location")
        status = resp.status
        conn.close()
        try:
            data = json.loads(payload.decode("utf-8")) if payload else None
        except ValueError:
            data = payload.decode("utf-8", errors="ignore")
        return status, data, loc

    def _paid_price(self, kind: str) -> int:
        row = self.db.get_conn().execute(
            "SELECT options_json FROM point_price_options WHERE kind=?", (kind,)
        ).fetchone()
        opts = [int(x) for x in json.loads(row[0] if isinstance(row[0], str) else json.dumps(row[0])) if int(x) > 0]
        return min(opts)

    def test_five_channels_synonyms_codes_highlights_and_reply_redirect(self):
        # 1. Code, #-prefixed code, and legacy code exact promotion
        for q, expected_code in (("FA-001", "FA-001"), ("#FA-001", "FA-001"), ("229", "FA-036"), ("SB-001", "SB-001"), ("C-01", "C-01")):
            status, res, _ = self._http("GET", f"/api/search?q={quote(q)}")
            self.assertEqual(status, 200)
            self.assertTrue(res["hits"], msg=f"No hits for {q}")
            self.assertEqual(res["hits"][0]["code"], expected_code)
            if expected_code == "C-01":
                self.assertEqual(res["hits"][0]["channel"], "colors")
                self.assertEqual(res["hits"][0]["url"], "/studio/?color=C-01")
            else:
                self.assertEqual(res["hits"][0]["url"], f"/t/{expected_code}")

        # 2. Custom published catalog asset, work + comment, and forum topic + reply with XSS sanitization
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO catalog_assets(
                    code, kind, source_type, author_username, author_name, name, group_name, tier, unlock_cost,
                    image_url, description, definition, prompt_en, secret_blackbox_prompt, status, published_at_ms, created_at, updated_at
                ) VALUES('USR-S99','style','community',?,?,'宋锦纹样国风测试','国风', 'free', 0, ?, '独特国风金线描边技法',
                         '绝密配方TOKEN_SECRET_DEF', 'EN_SECRET_DEF', 'BLACKBOX_SECRET_999', 'published', 1700000100000, CURRENT_TIMESTAMP::text, CURRENT_TIMESTAMP::text)""",
                (self.member["username"], self.member.get("display_name") or self.member["username"], self.IMG),
            )
        w = publish_work_direct(
            self.db,
            self.member,
            {
                "title": "金箔水彩森林作品展示",
                "prompt": "透明水彩晕染，金色光斑，柔和留白",
                "notes": "手绘纸本水彩实验笔记",
                "images": [self.IMG],
                "styles": ["FA-013"],
            },
        )
        S.add_comment_to_work(self.db, self.outsider, w["workId"], "水彩纸张克重建议300g")
        t = S.publish_forum_topic_post(
            self.db,
            self.member,
            {
                "category": "experience",
                "title": "工笔画与<script>alert(1)</script>线稿经验贴",
                "body": "主帖讨论铅笔线稿与控墨技巧，适合新手学习。",
            },
        )
        rep = S.publish_forum_reply_post(
            self.db,
            self.outsider,
            t["topicId"],
            "回复补充：云端渲染水彩纸纹理参数实测有用<img src=x onerror=alert(9)>",
        )
        self.worker.process_events()

        # Synonym match: 中国风 matches USR-S99 (description/title has 国风), never includes secret definition
        status, syn_res, _ = self._http("GET", "/api/search?channel=styles&q=" + quote("中国风"))
        self.assertEqual(status, 200)
        codes = [h["code"] for h in syn_res["hits"]]
        self.assertIn("USR-S99", codes)
        status, sec_res, _ = self._http("GET", "/api/search?q=BLACKBOX_SECRET_999")
        self.assertEqual(status, 200)
        self.assertEqual(sec_res["hits"], [])

        # Work & work comment search
        status, work_res, _ = self._http("GET", "/api/search?channel=works&q=" + quote("300g"))
        self.assertEqual(status, 200)
        self.assertTrue(any(h["url"].startswith(f"/t/{w['workId']}") for h in work_res["hits"]))

        # Forum reply hit + distinct merge + HTML stripping + /t/<topic>?reply=<rid> 302 redirect
        status, forum_res, _ = self._http("GET", "/api/search?channel=forum&q=" + quote("水彩纸纹理"))
        self.assertEqual(status, 200)
        matched = [h for h in forum_res["hits"] if h["url"].startswith(f"/t/{t['topicId']}")]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["url"], f"/t/{t['topicId']}?reply={rep['replyId']}")
        snippet_text = "".join(p["text"] for p in matched[0]["snippetParts"])
        self.assertNotIn("<script", snippet_text)
        self.assertNotIn("<img", snippet_text)
        self.assertTrue(any(p["match"] for p in matched[0]["snippetParts"]))

        redir_status, _, loc = self._http("GET", f"/t/{t['topicId']}?reply={rep['replyId']}")
        self.assertEqual(redir_status, 302)
        self.assertIn(f"view=topic&id={t['topicId']}", loc)
        self.assertIn(f"reply={rep['replyId']}", loc)

    def test_newest_sorting_pagination_and_tampered_cursor(self):
        # Publish 4 items across works and forum with distinct chronological timestamps
        published_urls = []
        for idx in range(3):
            tp = S.publish_forum_topic_post(
                self.db,
                self.member,
                {
                    "category": "experience",
                    "title": f"茶话会水彩专题排序验证第{idx}篇",
                    "body": f"共性检索词云雾水彩排序验证正文 {idx}",
                },
            )
            published_urls.append(f"/t/{tp['topicId']}")
        wk = publish_work_direct(
            self.db,
            self.member,
            {
                "title": "最新云雾水彩作品压轴发布",
                "prompt": "共性检索词云雾水彩排序验证",
                "images": [self.IMG],
                "styles": ["FA-013"],
            },
        )
        # Force deterministic timestamps so newest cross-channel sort order is unambiguous.
        with self.db.transaction() as tx:
            tx.execute("UPDATE forum_topics SET published_at_ms=2000 WHERE id=?", (published_urls[0].split("/")[-1],))
            tx.execute("UPDATE forum_topics SET published_at_ms=4000 WHERE id=?", (published_urls[1].split("/")[-1],))
            tx.execute("UPDATE forum_topics SET published_at_ms=3000 WHERE id=?", (published_urls[2].split("/")[-1],))
            tx.execute("UPDATE works SET published_at_ms=5000 WHERE id=?", (wk["workId"],))
        self.worker.process_events()

        status, p1, _ = self._http("GET", "/api/search?sort=newest&limit=2&q=" + quote("云雾水彩"))
        self.assertEqual(status, 200)
        self.assertEqual(len(p1["hits"]), 2)
        self.assertTrue(p1["hasMore"])
        self.assertGreaterEqual(p1["hits"][0]["publishedAtMs"], p1["hits"][1]["publishedAtMs"])
        self.assertEqual(p1["hits"][0]["channel"], "works")

        status, p2, _ = self._http(
            "GET", f"/api/search?sort=newest&limit=2&q={quote('云雾水彩')}&cursor={quote(p1['nextCursor'])}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(p2["hits"]), 2)
        self.assertEqual([h["publishedAtMs"] for h in [*p1["hits"], *p2["hits"]]], [5000, 4000, 3000, 2000])

        # Tampered cursor rejected cleanly
        bad_cursor = p1["nextCursor"][:-4] + "0000"
        status, err, _ = self._http("GET", f"/api/search?sort=newest&limit=2&q={quote('云雾水彩')}&cursor={quote(bad_cursor)}")
        self.assertEqual(status, 400)
        self.assertEqual(err["code"], "invalid_search_cursor")

    def test_private_board_permissions_immediate_revocation_and_paid_protection(self):
        board_key = B.save_board(self.db, self.admin, {"label": "内部机密研讨", "visibility": "private"})["key"]
        B.change_members(self.db, self.admin, board_key, {"usernames": [self.member["username"]]})
        priv_topic = S.publish_forum_topic_post(
            self.db,
            self.member,
            {
                "category": board_key,
                "title": "内部绝密彩铅配方分析帖",
                "body": "内部关键词星辰琥珀矿石仅成员可读",
            },
        )
        # Also create second hit for cursor revocation check
        S.publish_forum_topic_post(
            self.db,
            self.member,
            {
                "category": board_key,
                "title": "内部绝密彩铅第二帖",
                "body": "内部关键词星辰琥珀矿石分页测试",
            },
        )
        paid_topic_price = self._paid_price("topic")
        paid_work = publish_work_direct(
            self.db,
            self.member,
            {
                "title": "付费作品公开标题星辰琥珀公开名",
                "prompt": "付费秘密提示词ONLY_SECRET_WORK_PROMPT_XYZ",
                "subject": "付费秘密主体ONLY_SECRET_SUBJECT_XYZ",
                "notes": "公开创作手记",
                "images": [self.IMG],
                "styles": ["FA-013"],
            },
        )
        # publish_work_direct disallows price != 0 on creation; simulate historical/DB-priced work.
        with self.db.transaction() as tx:
            tx.execute("UPDATE works SET price = 10 WHERE id = ?", (paid_work["workId"],))
        paid_topic = S.publish_forum_topic_post(
            self.db,
            self.member,
            {
                "category": "experience",
                "title": "付费干货贴公开标题",
                "summary": "免费试读导语部分内容",
                "body": "免费试读<div class=\"hw-paywall-divider\"></div>付费干货核心秘密SECRET_LOCKED_TOPIC_XYZ",
                "price": paid_topic_price,
            },
        )
        # Short paid topic without explicit summary (tests hw-paywall-divider truncation fallback)
        S.publish_forum_topic_post(
            self.db,
            self.member,
            {
                "category": "experience",
                "title": "短贴付费干货公开标题",
                "body": "试读<div class=\"hw-paywall-divider\"></div>短贴秘密SHORT_PAID_SECRET_XYZ",
                "price": paid_topic_price,
            },
        )
        # Unpublished draft studio canvas/generation stays excluded
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO studio_canvases(id,user_id,name,graph_json) VALUES('cv_priv',?,'私人创作画布UNLISTED_CANVAS_SECRET','{}'::jsonb)",
                (self.member["id"],),
            )
            tx.execute(
                "INSERT INTO studio_generations(id,user_id,username,tab_title,prompt,status,created_at) VALUES('gen_priv',?,?,'私人工作流','私人生成记录UNLISTED_GEN_SECRET','queued',CURRENT_TIMESTAMP::text)",
                (self.member["id"], self.member["username"]),
            )
        self.worker.process_events()

        # Paid secrets & private studio canvases must NEVER enter index or search hits (even for author/admin)
        for secret in ("ONLY_SECRET_WORK_PROMPT_XYZ", "ONLY_SECRET_SUBJECT_XYZ", "SECRET_LOCKED_TOPIC_XYZ", "SHORT_PAID_SECRET_XYZ", "UNLISTED_CANVAS_SECRET", "UNLISTED_GEN_SECRET"):
            for tok in (self.member_token, self.admin_token, self.outsider_token):
                status, res, _ = self._http("GET", "/api/search?q=" + quote(secret), token=tok)
                self.assertEqual(status, 200)
                self.assertEqual(res["hits"], [], msg=f"Secret leaked for {secret}")
        # Public title of paid work IS searchable
        status, pw_res, _ = self._http("GET", "/api/search?channel=works&q=" + quote("星辰琥珀公开名"))
        self.assertEqual(status, 200)
        self.assertTrue(any(h["url"] == f"/t/{paid_work['workId']}" for h in pw_res["hits"]))

        # Private board visible to member (with cursor pagination), invisible to outsider & guest
        status, m_res, _ = self._http("GET", "/api/search?limit=1&q=" + quote("星辰琥珀矿石"), token=self.member_token)
        self.assertEqual(status, 200)
        self.assertEqual(len(m_res["hits"]), 1)
        self.assertTrue(m_res["hasMore"])
        saved_cursor = m_res["nextCursor"]
        for tok in (None, self.outsider_token):
            status, o_res, _ = self._http("GET", "/api/search?q=" + quote("星辰琥珀矿石"), token=tok)
            self.assertEqual(status, 200)
            self.assertEqual(o_res["hits"], [])

        # Revoke membership WITHOUT running worker: search & old cursor must block immediately!
        B.change_members(self.db, self.admin, board_key, {"action": "revoke", "usernames": [self.member["username"]]})
        status, after_revoke, _ = self._http("GET", "/api/search?q=" + quote("星辰琥珀矿石"), token=self.member_token)
        self.assertEqual(status, 200)
        self.assertEqual(after_revoke["hits"], [])
        status, cursor_err, _ = self._http(
            "GET", f"/api/search?limit=1&q={quote('星辰琥珀矿石')}&cursor={quote(saved_cursor)}", token=self.member_token
        )
        self.assertEqual(status, 400)
        self.assertEqual(cursor_err["code"], "invalid_search_cursor")

        # Restore visibility on public topic after hide -> delete -> restore roundtrip
        from backend.admin_services import admin_moderate_topic
        pub_t = S.publish_forum_topic_post(
            self.db, self.member, {"category": "experience", "title": "隐藏恢复测试主帖标题", "body": "独特校验词翡翠釉色测试"}
        )
        self.worker.process_events()
        self.assertTrue(self._http("GET", "/api/search?q=" + quote("翡翠釉色"))[1]["hits"])
        admin_moderate_topic(self.db, self.admin, pub_t["topicId"], "hide")
        # Immediate block before worker + remains absent after worker
        self.assertEqual(self._http("GET", "/api/search?q=" + quote("翡翠釉色"))[1]["hits"], [])
        self.worker.process_events()
        self.assertEqual(self._http("GET", "/api/search?q=" + quote("翡翠釉色"))[1]["hits"], [])
        admin_moderate_topic(self.db, self.admin, pub_t["topicId"], "publish")
        self.worker.process_events()
        self.assertTrue(self._http("GET", "/api/search?q=" + quote("翡翠釉色"))[1]["hits"])
        admin_moderate_topic(self.db, self.admin, pub_t["topicId"], "delete")
        self.assertEqual(self._http("GET", "/api/search?q=" + quote("翡翠釉色"))[1]["hits"], [])
        self.worker.process_events()
        self.assertEqual(self._http("GET", "/api/search?q=" + quote("翡翠釉色"))[1]["hits"], [])

    def test_triggers_ignore_counters_and_outage_retry_backoff(self):
        wk = publish_work_direct(
            self.db,
            self.member,
            {"title": "计数忽略与重试测试作品", "prompt": "独特词汇琥珀琉璃笔触", "images": [self.IMG]},
        )
        self.worker.process_events()
        before_cnt = self.db.get_conn().execute(
            "SELECT count(*) FROM search_events WHERE entity_id=?", (wk["workId"],)
        ).fetchone()[0]
        # Counter-only UPDATE must NOT enqueue redundant outbox events
        with self.db.transaction() as tx:
            tx.execute("UPDATE works SET views=views+10, likes=likes+2 WHERE id=?", (wk["workId"],))
        after_cnt = self.db.get_conn().execute(
            "SELECT count(*) FROM search_events WHERE entity_id=?", (wk["workId"],)
        ).fetchone()[0]
        self.assertEqual(after_cnt, before_cnt)

        # Simulate search outage on read & write paths without breaking other DB endpoints
        if self.meili is not None:
            self.meili.state.down = True
            self._simulate_outage_and_retry(wk["workId"])
        else:
            with patch.dict(os.environ, {"HANDRAW_SEARCH_URL": "http://127.0.0.1:1"}):
                self._simulate_outage_and_retry(wk["workId"], unreachable_mode=True)

    def _simulate_outage_and_retry(self, work_id: str, *, unreachable_mode: bool = False):
        status, err, _ = self._http("GET", "/api/search?q=test")
        self.assertEqual(status, 503)
        self.assertEqual(err["code"], "search_unavailable")
        self.assertNotIn("test_read_key", json.dumps(err))

        st_status, adm, _ = self._http("GET", "/api/admin/search", token=self.admin_token)
        self.assertEqual(st_status, 200)
        self.assertFalse(adm["available"])

        # Unauthorized member gets 403 on admin search endpoints
        self.assertEqual(self._http("GET", "/api/admin/search", token=self.member_token)[0], 403)
        self.assertEqual(self._http("POST", "/api/admin/search/retry", token=self.member_token, body={})[0], 403)

        # Update title during outage -> worker records failure & backoff, never drops event
        with self.db.transaction() as tx:
            tx.execute("UPDATE works SET title='失败重试恢复后的新标题' WHERE id=?", (work_id,))
        if unreachable_mode:
            failing_worker = SearchWorker(self.db, engine=SearchEngine(write=True))
            failing_worker.process_events()
        else:
            self.meili.state.down = False
            self.meili.state.fail_next_writes = 1
            self.worker.process_events()
        ev = self.db.get_conn().execute(
            "SELECT * FROM search_events WHERE entity_id=? ORDER BY id DESC LIMIT 1", (work_id,)
        ).fetchone()
        self.assertIsNone(ev["processed_at"])
        self.assertGreaterEqual(ev["attempts"], 1)
        self.assertTrue(ev["error"])

        # Admin retry resets retry_at & logs audit entry, then worker succeeds
        r_status, r_res, _ = self._http("POST", "/api/admin/search/retry", token=self.admin_token, body={})
        self.assertEqual(r_status, 200)
        self.assertTrue(r_res["ok"])
        audit = self.db.get_conn().execute(
            "SELECT * FROM audit_logs WHERE action='search_retry' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(audit)
        if not unreachable_mode:
            self.worker.process_events()
            hit = self._http("GET", "/api/search?channel=works&q=" + quote("失败重试恢复后的新标题"))[1]["hits"]
            self.assertEqual(len(hit), 1)

    def test_single_channel_and_concurrent_rebuild_atomic_swap(self):
        # Baseline item in styles stays intact during forum-only rebuild
        style_before = self._http("GET", "/api/search?channel=styles&q=FA-001")[1]["hits"]
        self.assertTrue(style_before)

        t_kept = S.publish_forum_topic_post(
            self.db, self.member, {"category": "experience", "title": "并发重建保留旧帖标题", "body": "并发测试锚点词青瓷"}
        )
        t_edited = S.publish_forum_topic_post(
            self.db, self.member, {"category": "experience", "title": "并发重建待改写帖标题", "body": "并发测试锚点词青瓷"}
        )
        t_deleted = S.publish_forum_topic_post(
            self.db, self.member, {"category": "experience", "title": "并发重建待删除帖标题", "body": "并发测试锚点词青瓷"}
        )
        self.worker.process_events()

        # Request two concurrent rebuilds for 'forum' -> deduplicated into one active job
        s1, j1, _ = self._http("POST", "/api/admin/search/rebuild", token=self.admin_token, body={"channel": "forum"})
        s2, j2, _ = self._http("POST", "/api/admin/search/rebuild", token=self.admin_token, body={"channel": "forum"})
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 200)
        self.assertEqual(j1["jobs"], j2["jobs"])

        created_mid_build = {}

        def mutate_during_snapshot(ch):
            self.assertEqual(ch, "forum")
            # Insert new topic, edit existing topic, delete existing topic while shadow index is between snapshot & swap
            new_t = S.publish_forum_topic_post(
                self.db, self.member, {"category": "experience", "title": "快照后并发新增主帖", "body": "并发测试锚点词青瓷 新增词琉璃盏"}
            )
            created_mid_build["id"] = new_t["topicId"]
            with self.db.transaction() as tx:
                tx.execute("UPDATE forum_topics SET title='快照后并发修改的新标题' WHERE id=?", (t_edited["topicId"],))
                tx.execute("UPDATE forum_topics SET status='deleted' WHERE id=?", (t_deleted["topicId"],))
            self.db.close_thread_conn()

        self.worker.after_snapshot = mutate_during_snapshot
        try:
            self._drain_worker()
        finally:
            self.worker.after_snapshot = None

        job = self.db.get_conn().execute("SELECT * FROM search_jobs WHERE id=?", (j1["jobs"][0],)).fetchone()
        self.assertEqual(job["status"], "succeeded")

        # Styles channel untouched
        self.assertTrue(self._http("GET", "/api/search?channel=styles&q=FA-001")[1]["hits"])
        # Swapped forum index reflects kept, edited, newly created, and deleted topics accurately!
        res = self._http("GET", "/api/search?channel=forum&q=" + quote("青瓷"))[1]["hits"]
        titles_by_url = {h["url"]: h["title"] for h in res}
        self.assertIn(f"/t/{t_kept['topicId']}", titles_by_url)
        self.assertEqual(titles_by_url.get(f"/t/{t_edited['topicId']}"), "快照后并发修改的新标题")
        self.assertIn(f"/t/{created_mid_build['id']}", titles_by_url)
        self.assertNotIn(f"/t/{t_deleted['topicId']}", titles_by_url)

        # Failed rebuild keeps previous live index serving
        if self.meili is not None:
            self.meili.state.fail_swap = True
            _, j_fail, _ = self._http("POST", "/api/admin/search/rebuild", token=self.admin_token, body={"channel": "forum"})
            self._drain_worker()
            fjob = self.db.get_conn().execute("SELECT * FROM search_jobs WHERE id=?", (j_fail["jobs"][0],)).fetchone()
            self.assertEqual(fjob["status"], "unknown")
            still_ok = self._http("GET", "/api/search?channel=forum&q=" + quote("琉璃盏"))[1]["hits"]
            self.assertTrue(still_ok)


if __name__ == "__main__":
    unittest.main()
