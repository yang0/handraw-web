"""Progressive masonry thumbnails are genuinely tiny, cached, and aspect-correct."""
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.server import THUMB_WIDTHS, build_thumbnail, normalize_thumb_width


class ProgressiveThumbnailTests(unittest.TestCase):
    def test_width_bucket_is_small_and_does_not_change_standard_cards(self):
        self.assertIn(48, THUMB_WIDTHS)
        self.assertEqual(normalize_thumb_width("48"), 48)
        self.assertEqual(normalize_thumb_width("32"), 48)
        self.assertEqual(normalize_thumb_width("240"), 320)
        self.assertEqual(normalize_thumb_width("500"), 640)

    def test_48px_webp_preserves_aspect_without_cropping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.png"
            Image.new("RGB", (960, 640), (87, 154, 211)).save(path)
            payload = build_thumbnail(path, 48)
            self.assertIsNotNone(payload)
            self.assertLess(len(payload), 5000, "the blurred preview should be cheap to transfer")
            with Image.open(io.BytesIO(payload)) as thumb:
                self.assertEqual(thumb.format, "WEBP")
                self.assertEqual(thumb.size, (48, 32))
            # Requested image larger than the source must not upscale the original.
            self.assertIsNone(build_thumbnail(path, 1280))


if __name__ == "__main__":
    unittest.main()
