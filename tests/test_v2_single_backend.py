"""One listener serves path-based local pages and Host-based deployed pages."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from backend.server import create_channel_server, init_database, main


class SingleBackendHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.env = patch.dict(os.environ, {"HANDRAW_DEMO_MODE":"1", "HANDRAW_ALLOWED_ORIGINS":"http://trusted.test", "HANDRAW_PRIVATE_STORAGE":str(root)})
        cls.env.start()
        cls.db = init_database(root / "isolated.db")
        cls.server = create_channel_server(0, "main", cls.db)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close()
        cls.env.stop()
        cls.folder.cleanup()

    def request(self, path, host=None, cookie=None, body=None):
        headers = {"Host":host or "localhost", "Origin":"http://trusted.test"}
        if cookie:
            headers["Cookie"] = cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, headers=headers, data=data)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_local_paths_and_legacy_html(self):
        for path, marker in [("/","main-app-root"),("/studio/","studio-app-root"),("/forum/","forum-app-root"),("/admin/","admin-root"),("/studio.html","studio-app-root"),("/forum.html","forum-app-root"),("/admin.html","admin-root")]:
            with self.subTest(path=path):
                status, _, raw = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn(marker.encode(), raw)
        self.assertEqual(self.request("/assets/shared.js")[0], 200)

    def test_production_hosts_use_one_listener(self):
        for host, marker in [("handraw-style.com","main-app-root"),("studio.handraw-style.com","studio-app-root"),("forum.handraw-style.com","forum-app-root"),("admin.handraw-style.com","admin-root")]:
            with self.subTest(host=host):
                status, _, raw = self.request("/", host=host)
                self.assertEqual(status, 200)
                self.assertIn(marker.encode(), raw)

    def test_session_shared_and_admin_api_still_guarded(self):
        self.assertEqual(self.request("/api/admin/dashboard")[0], 401)
        status, headers, _ = self.request("/api/auth/login", body={"account":"sprout_xia","password":"handraw123"})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";",1)[0]
        for host in ["localhost","studio.handraw-style.com","forum.handraw-style.com"]:
            status, _, raw = self.request("/api/boot", host=host, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)["loggedIn"])
        self.assertEqual(self.request("/api/admin/dashboard", host="admin.handraw-style.com", cookie=cookie)[0], 403)


class SingleBackendStartupTests(unittest.TestCase):
    def test_main_creates_exactly_one_server(self):
        db, server, reconciler = Mock(), Mock(), Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch("backend.server.init_database", return_value=db), patch("backend.server.create_channel_server", return_value=server) as create, patch("backend.server.GenerationReconciler") as factory, patch("builtins.print"):
            factory.return_value.start.return_value = reconciler
            main(["--port","8127"])
        create.assert_called_once_with(8127,"main",db,host=None,demo_mode=None)
        server.server_close.assert_called_once()
        reconciler.stop.assert_called_once()
        db.close.assert_called_once()
