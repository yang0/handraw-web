"""Contract tests for private gallery Base64 upload body limits (Issue #91)."""
from __future__ import annotations

import io
import unittest

from backend.server import HandrawRequestHandler
from backend.services import ServiceError


class GalleryUploadBodyLimitsTests(unittest.TestCase):
    def _handler(self, path: str, length: int, authenticated: bool):
        handler = object.__new__(HandrawRequestHandler)
        handler.path = path
        handler.command = "PUT"
        handler.headers = {"Content-Length": str(length)}
        handler.rfile = io.BytesIO(b"{}")
        handler._body_consumed = False
        handler._current_user = lambda required=False: {"id": 1} if authenticated else None
        return handler

    def test_authenticated_library_put_allows_base64_headroom(self):
        # A 15 MiB binary expands to just over 20 MiB in JSON/Base64 form.
        handler = self._handler(
            "/api/library/assets/11111111-1111-4111-8111-111111111111",
            21 * 1024 * 1024, True,
        )
        self.assertEqual(handler._read_json_body(), {})

    def test_same_body_still_rejected_when_unauthenticated(self):
        handler = self._handler(
            "/api/library/assets/11111111-1111-4111-8111-111111111111",
            21 * 1024 * 1024, False,
        )
        with self.assertRaises(ServiceError) as ctx:
            handler._read_json_body()
        self.assertEqual(ctx.exception.status, 413)

    def test_other_put_routes_keep_normal_limit(self):
        handler = self._handler("/api/studio/recipes/123", 21 * 1024 * 1024, True)
        with self.assertRaises(ServiceError) as ctx:
            handler._read_json_body()
        self.assertEqual(ctx.exception.status, 413)

    def test_gallery_limit_remains_bounded(self):
        handler = self._handler(
            "/api/library/assets/11111111-1111-4111-8111-111111111111",
            25 * 1024 * 1024, True,
        )
        with self.assertRaises(ServiceError) as ctx:
            handler._read_json_body()
        self.assertEqual(ctx.exception.status, 413)


if __name__ == "__main__":
    unittest.main()
