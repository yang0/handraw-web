"""Every cached private derivative must pass original-media authorization."""

import http.client
import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from backend import server as web
from backend.services import register_user
from tests.postgres_support import open_isolated_postgres


class ImageVariantHttpTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(
                os.environ,
                {"HANDRAW_PRIVATE_STORAGE": str(self.root), "HANDRAW_DEMO_MODE": "0"},
            )
        )
        public = self.root / "public"
        public.mkdir()
        self.public = public / "source.jpg"
        Image.effect_noise((1600, 1000), 45).convert("RGB").save(
            self.public, quality=95
        )
        self.enterContext(patch.object(web, "DEFAULT_STYLE_IMAGES_DIR", public))
        self.db = open_isolated_postgres(self)
        self.owner, self.token = register_user(
            self.db, "image_owner", "FixturePass123!"
        )
        self.other, self.other_token = register_user(
            self.db, "image_other", "FixturePass123!"
        )
        uploads = self.root / "uploads"
        uploads.mkdir()
        self.private = uploads / "private.jpg"
        self.private.write_bytes(self.public.read_bytes())
        self.db.get_conn().execute(
            "INSERT INTO user_uploads(id,user_id,cat,name_zh,image_url,file_path,bytes,created_at,updated_at) VALUES('private',?,'other','Private','/uploads/private.jpg',?,?,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)",
            (self.owner["id"], str(self.private), self.private.stat().st_size),
        )
        self.server = web.create_channel_server(
            0, "main", self.db, host="127.0.0.1", demo_mode=False
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, token=None, etag=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=15
        )
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if etag:
            headers["If-None-Match"] = etag
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_public_sizes_revalidate_and_source_change_replaces_cached_pixels(self):
        etags = []
        for width in (96, 320, 960):
            status, headers, data = self.get(f"/images/source.jpg?w={width}")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "image/webp")
            self.assertIn("no-cache", headers["Cache-Control"])
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.width, width)
            self.assertLess(len(data), self.public.stat().st_size)
            etags.append(headers["ETag"])
        self.assertEqual(len(set(etags)), 3)
        status, _, body = self.get("/images/source.jpg?w=320", etag=etags[1])
        self.assertEqual((status, body), (304, b""))
        Image.new("RGB", (1600, 1000), "red").save(self.public)
        status, headers, _ = self.get("/images/source.jpg?w=320", etag=etags[1])
        self.assertEqual(status, 200)
        self.assertNotEqual(headers["ETag"], etags[1])
        status, _, body = self.get("/images/source.jpg")
        self.assertEqual(body, self.public.read_bytes())

    def test_cached_private_sizes_remain_owner_only_and_do_not_escape_by_query_or_etag(
        self,
    ):
        for width in (96, 640):
            path = f"/uploads/private.jpg?w={width}"
            status, headers, body = self.get(path, self.token)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "private, no-store")
            with Image.open(io.BytesIO(body)) as image:
                self.assertEqual(image.width, width)
            self.assertTrue(list((self.root / "thumbs").glob("*.webp")))
            self.assertEqual(self.get(path)[0], 404)
            self.assertEqual(self.get(path, self.other_token)[0], 404)
            self.assertEqual(self.get(path, self.other_token, '"guessed"')[0], 404)
        self.private.unlink()
        self.assertEqual(self.get("/uploads/private.jpg?w=640", self.token)[0], 404)
