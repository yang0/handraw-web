"""Dimension cache preserves media sandbox rules and refreshes on replacement."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend import media_dims


class MediaDimensionsCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self._patch = patch.object(media_dims, "get_uploads_dir", return_value=self.root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        media_dims._cached_image_size.cache_clear()
        self.addCleanup(media_dims._cached_image_size.cache_clear)

    def test_same_image_reuses_header_probe(self):
        Image.new("RGB", (80, 60)).save(self.root / "source.png")
        with patch.object(media_dims.Image, "open", wraps=Image.open) as opened:
            self.assertEqual(media_dims.image_size("/uploads/source.png"), (80, 60))
            self.assertEqual(media_dims.image_size("/uploads/source.png?width=48"), (80, 60))
            self.assertEqual(opened.call_count, 1)

    def test_replacing_file_invalidates_cached_dimensions(self):
        path = self.root / "updated.png"
        Image.new("RGB", (50, 80)).save(path)
        self.assertEqual(media_dims.image_size("/uploads/updated.png"), (50, 80))
        Image.new("RGB", (100, 10)).save(path)
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000_000))
        self.assertEqual(media_dims.image_size("/uploads/updated.png"), (100, 10))

    def test_missing_then_created_file_recovers(self):
        self.assertIsNone(media_dims.image_size("/uploads/later.png"))
        Image.new("RGB", (70, 40)).save(self.root / "later.png")
        self.assertEqual(media_dims.image_size("/uploads/later.png"), (70, 40))

    def test_unreadable_file_recovers_after_replacement(self):
        path = self.root / "broken.png"
        path.write_bytes(b"not a real image")
        self.assertIsNone(media_dims.image_size("/uploads/broken.png"))
        Image.new("RGB", (12, 36)).save(path)
        self.assertEqual(media_dims.image_size("/uploads/broken.png"), (12, 36))

    def test_traversal_and_external_urls_are_never_probed(self):
        with patch.object(media_dims.Image, "open", wraps=Image.open) as opened:
            self.assertIsNone(media_dims.image_size("/uploads/../outside.png"))
            self.assertIsNone(media_dims.image_size("https://example.com/image.png"))
            self.assertEqual(opened.call_count, 0)

    def test_cache_is_bounded(self):
        self.assertEqual(media_dims._cached_image_size.cache_info().maxsize, 2048)


if __name__ == "__main__":
    unittest.main()
