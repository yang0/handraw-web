"""Studio startup keeps resource rights while avoiding the community feed."""

import gzip
import http.client
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.server import create_channel_server
from backend.services import build_boot_payload, register_user
from backend.static_assets import accepts_gzip, file_representation
from tests.postgres_support import open_isolated_postgres


class StudioStartupTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict("os.environ", {"HANDRAW_DEMO_MODE": "0"}))
        self.db = open_isolated_postgres(self, seed=True)
        self.user, _ = register_user(self.db, "startup_user", "FixturePass123!")

    def test_studio_boot_preserves_catalog_permissions_and_account_without_community_scans(
        self,
    ):
        full = build_boot_payload(self.db, self.user)
        conn = self.db.get_conn()
        with (
            patch.object(conn, "execute", wraps=conn.execute) as execute,
            patch(
                "backend.services.compute_public_asset_counts_and_creators",
                side_effect=AssertionError("unneeded public aggregation"),
            ),
            patch(
                "backend.resource_discussions.apply_boot",
                side_effect=AssertionError("unneeded discussion hydration"),
            ),
        ):
            studio = build_boot_payload(self.db, self.user, surface="studio")
        for key in (
            "user",
            "credits",
            "economy",
            "collections",
            "unlockedIds",
            "exclusiveResources",
            "communityResources",
            "officialOverrides",
            "officialResources",
            "myResources",
            "pendingResources",
            "officialPresets",
            "billing",
        ):
            self.assertEqual(studio[key], full[key], key)
        self.assertEqual(studio["works"], [])
        self.assertEqual(studio["topics"], [])
        self.assertEqual(studio["assetComments"], {})
        self.assertFalse(
            any(
                "SELECT * FROM forum_replies" in str(call.args[0])
                for call in execute.call_args_list
            )
        )
        self.assertFalse(
            any(
                "SELECT * FROM work_comments" in str(call.args[0])
                for call in execute.call_args_list
            )
        )

    def test_guest_boot_contains_no_private_account_or_authored_drafts(self):
        payload = build_boot_payload(self.db, None, surface="studio")
        self.assertFalse(payload["loggedIn"])
        self.assertIsNone(payload["economy"])
        self.assertEqual(payload["myResources"], [])
        self.assertEqual(payload["unlockedIds"], [])
        self.assertEqual(payload["works"], [])

    def test_public_source_gzip_conditional_requests_and_private_api_cache_policy(self):
        server = create_channel_server(
            0, "main", self.db, host="127.0.0.1", demo_mode=False
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def get(path, headers=None):
            client = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=15
            )
            try:
                client.request("GET", path, headers=headers or {})
                response = client.getresponse()
                headers = dict(response.getheaders())
                headers["Vary"] = ", ".join(response.headers.get_all("Vary", []))
                return response.status, headers, response.read()
            finally:
                client.close()

        status, headers, encoded = get(
            "/assets/studio-app.js?v=startup-test", {"Accept-Encoding": "gzip"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", headers["Vary"])
        raw = (Path(__file__).parents[1] / "demo/assets/studio-app.js").read_bytes()
        self.assertEqual(gzip.decompress(encoded), raw)
        self.assertLess(len(encoded), len(raw) // 3)
        status, _, body = get(
            "/assets/studio-app.js?v=startup-test",
            {"Accept-Encoding": "gzip", "If-None-Match": headers["ETag"]},
        )
        self.assertEqual((status, body), (304, b""))
        status, plain_headers, plain = get(
            "/assets/studio-app.js", {"Accept-Encoding": "gzip;q=0"}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("Content-Encoding", plain_headers)
        self.assertEqual(plain, raw)
        self.assertEqual(plain_headers["Cache-Control"], "public, no-cache")
        self.assertNotEqual(plain_headers["ETag"], headers["ETag"])
        status, catalog_headers, compressed_catalog = get(
            "/data/catalog.json", {"Accept-Encoding": "gzip"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(catalog_headers["Content-Encoding"], "gzip")
        catalog = json.loads(gzip.decompress(compressed_catalog))
        self.assertTrue(catalog["resources"])
        self.assertTrue(
            all("definition" not in resource for resource in catalog["resources"])
        )
        status, _, body = get(
            "/data/catalog.json",
            {"Accept-Encoding": "gzip", "If-None-Match": catalog_headers["ETag"]},
        )
        self.assertEqual((status, body), (304, b""))
        status, api_headers, body = get("/api/boot?surface=studio")
        self.assertEqual(status, 200)
        self.assertEqual(api_headers["Cache-Control"], "no-store")
        self.assertFalse(json.loads(body)["loggedIn"])


class StaticRepresentationTests(unittest.TestCase):
    def test_negotiation_and_file_change_invalidate_cached_representation(self):
        for value in ("gzip;q=0, *;q=1", "br", "gzip;q=invalid"):
            self.assertFalse(accepts_gzip(value))
        self.assertTrue(accepts_gzip("br, gzip;q=0.8"))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "source.js"
            path.write_bytes(b"old content" * 200)
            before = file_representation(path, "gzip")
            path.write_bytes(b"new content" * 220)
            after = file_representation(path, "gzip")
            self.assertNotEqual(before[2], after[2])
            self.assertEqual(gzip.decompress(after[0]), path.read_bytes())
