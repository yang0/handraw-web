"""Registration and login rate limits must key on the real visitor.

Behind the project's nginx deployment every request arrives from 127.0.0.1, so a
limit keyed on the socket address lumps all visitors together: one person
registering a few times locks out everyone else.  The forwarded header is only
trusted when the connection already comes from the local proxy.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.postgres_support import open_isolated_postgres
from backend import server as server_module
from backend.server import create_channel_server


class ClientIpResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0", "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"})
        cls._env.start()
        cls.temp = TemporaryDirectory()
        cls.db = open_isolated_postgres(cls, seed=True)
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.db.close_thread_conn()
        cls.db.get_conn().close()
        cls.db.close()
        cls.temp.cleanup()
        cls._env.stop()

    def _register(self, username, headers=None):
        payload = json.dumps({"username": username, "password": "rate-limit-pass"}).encode()
        request = urllib.request.Request(
            self.base + "/api/auth/register",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": "http://trusted.test", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def test_a_forwarded_client_is_limited_separately(self):
        # Simulate two different visitors behind the proxy by sending distinct
        # X-Real-IP values from the loopback connection.
        with patch.dict(os.environ, {"HANDRAW_ALLOWED_ORIGINS": "http://trusted.test"}):
            first = [self._register(f"ip_a_{i}", {"X-Real-IP": "203.0.113.10"}) for i in range(8)]
            second = [self._register(f"ip_b_{i}", {"X-Real-IP": "203.0.113.20"}) for i in range(2)]
        self.assertIn(429, first, "the first forwarded client should hit its own limit")
        self.assertTrue(
            all(code == 200 for code in second),
            f"a different forwarded client must not inherit the first one's limit: {second}",
        )

    def test_forwarded_header_is_ignored_from_a_remote_peer(self):
        # A direct client (not the local proxy) must not be able to pick its own
        # bucket by spoofing the header.
        handler = self.server.RequestHandlerClass
        fake = object.__new__(handler)
        fake.client_address = ("198.51.100.7", 1234)
        fake.headers = {"X-Real-IP": "10.9.9.9", "X-Forwarded-For": "10.8.8.8"}
        self.assertEqual(handler._client_ip(fake), "198.51.100.7")

    def test_loopback_peer_honours_the_forwarded_header(self):
        handler = self.server.RequestHandlerClass
        fake = object.__new__(handler)
        fake.client_address = ("127.0.0.1", 1234)
        fake.headers = {"X-Forwarded-For": "203.0.113.10, 127.0.0.1"}
        self.assertEqual(handler._client_ip(fake), "203.0.113.10")


if __name__ == "__main__":
    unittest.main()
