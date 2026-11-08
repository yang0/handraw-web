"""#119 real HTTP Run recovery: authenticated, restart-safe, cancel-safe."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.server import HandrawRequestHandler, SESSION_COOKIE_NAME, init_database
from backend.generation_v3 import ensure_run
from backend.services import register_user


class RuntimeHttp119Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "runtime119.db"
        self.env = patch.dict(os.environ, {
            "HANDRAW_DB_PATH": str(self.path), "HANDRAW_DEMO_MODE": "1",
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
            "HANDRAW_UPLOADS_DIR": str(Path(self.tmp.name) / "uploads"),
            "HANDRAW_GENERATED_DIR": str(Path(self.tmp.name) / "generated"),
        })
        self.env.start()
        self.db = init_database(self.path)
        self.owner, token = register_user(self.db, "runtime_http_119", "Pass12345!")
        self.stranger, other = register_user(self.db, "runtime_http_other", "Pass12345!")
        self.cookie = SESSION_COOKIE_NAME + "=" + token
        self.other_cookie = SESSION_COOKIE_NAME + "=" + other
        with self.db.transaction() as tx:
            self.run_id = ensure_run(
                tx, user_id=int(self.owner["id"]), source="web",
                external_run_id="runtime-http-119", expected_count=6,
            )
            for i in (0, 1, 2):
                tx.execute(
                    """INSERT INTO generation_items
                       (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                       VALUES (?,?,?,'pending',NULL,'','2026-11-08','2026-11-08')""",
                    (f"pending-{i}", self.run_id, i * 1000),
                )
            tx.execute(
                """INSERT INTO studio_generations
                   (id,user_id,username,tab_title,mode,prompt,items_json,engine,
                    status,created_at,batch_id,batch_index,batch_total,task_id,request_id)
                   VALUES (?,?,?,?,?,'','[]','live',?,?,?,?,?,?,?)""",
                ("attempt-http-119", int(self.owner["id"]), self.owner["username"],
                 "Canvas", "pure", "queued", "2026-11-08",
                 "runtime-http-119", 3, 6, "task-remote-119", "req-remote-119"),
            )
        self._start()

    def _start(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), HandrawRequestHandler)
        self.httpd.db = self.db
        self.httpd.channel_role = "main"
        self.httpd.allow_demo_routes = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)

    def tearDown(self):
        self._stop()
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def _request(self, method, route, body=None, cookie=None):
        headers = {"Origin":"http://trusted.test","Content-Type":"application/json"}
        if cookie: headers["Cookie"] = cookie
        payload = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base+route, data=payload,
                                     method=method, headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=12) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_owner_run_auth_cancel_only_unsubmitted_and_restart_read(self):
        route = "/api/studio/runs/" + self.run_id
        status, data = self._request("GET", route, cookie=self.cookie)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["projection"]["total"], 6)
        self.assertEqual(data["projection"]["succeeded"], 0)
        self.assertEqual(len(data["slots"]), 6)
        self.assertEqual(data["attempts"][0]["requestId"], "req-remote-119")
        self.assertTrue(data["slots"][3]["needsRecheck"])
        self.assertEqual(self._request("GET",route,cookie=self.other_cookie)[0],404)
        self.assertEqual(self._request("GET",route)[0],401)
        cancel = "/api/studio/batches/runtime-http-119/cancel-pending"
        status, result = self._request("POST",cancel,
            {"positions":[0,1,3]},self.cookie)
        self.assertEqual(status,200,result)
        self.assertEqual(result["cancelledPositions"],[0,1])
        self.assertEqual(result["alreadySubmittedPositions"],[3])
        self.assertFalse(result["remoteTasksCancelled"])
        self.assertEqual(self._request("POST",cancel,
            {"positions":[2]},self.other_cookie)[0],404)

        # A real server handler restart must preserve V3 states and attempts.
        self._stop()
        self.db.close()
        self.db = init_database(self.path)
        self._start()
        status, restored = self._request("GET",route,cookie=self.cookie)
        self.assertEqual(status,200,restored)
        self.assertEqual(restored["projection"]["total"],6)
        self.assertEqual(restored["projection"]["cancelled"],2)
        self.assertEqual(restored["slots"][3]["taskId"],"task-remote-119")
        self.assertEqual(restored["run"]["id"],self.run_id)


if __name__ == "__main__":
    unittest.main()
