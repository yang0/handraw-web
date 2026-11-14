"""Derivatives are stable across workers and never grant access to the original."""

import concurrent.futures
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from backend import image_variants as variants


class ImageVariantTests(unittest.TestCase):
    def test_browser_and_server_share_the_same_bounded_width_contract(self):
        source=(Path(__file__).parents[1]/'demo/assets/image-loader.js').read_text(encoding='utf-8')
        contract=re.search(r'const WIDTHS = \[([^]]+)\]',source).group(1)
        self.assertEqual(tuple(int(width.strip()) for width in contract.split(',')),variants.THUMB_WIDTHS)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cache = self.root / "thumbs"
        self.enterContext(
            patch.dict(os.environ, {"HANDRAW_THUMB_CACHE_DIR": str(self.cache)})
        )
        self.source = self.root / "photo.png"
        Image.effect_noise((1800, 1200), 40).convert("RGB").save(self.source)

    def test_sizes_compression_and_cache_hit_without_reencoding(self):
        for width in (48, 96, 240, 640, 1280, 2560):
            body, kind, resized = variants.read_with_thumbnail(self.source, width)
            self.assertTrue(resized)
            self.assertEqual(kind, "image/webp")
            with Image.open(io.BytesIO(body)) as image:
                self.assertEqual(image.width, min(1800, width))
                self.assertAlmostEqual(image.width / image.height, 1.5, delta=0.03)
            self.assertLess(len(body), self.source.stat().st_size)
        with patch.object(
            variants, "build_thumbnail", side_effect=AssertionError("cache miss")
        ):
            cached, _, _ = variants.read_with_thumbnail(self.source, 640)
        self.assertTrue(cached)
        self.assertEqual(len(list(self.cache.glob("*.webp"))), 6)

    def test_replaced_source_invalidates_variant_and_original_is_unchanged(self):
        original = self.source.read_bytes()
        first, _, _ = variants.read_with_thumbnail(self.source, 240)
        self.assertEqual(self.source.read_bytes(), original)
        Image.new("RGB", (1800, 1200), "red").save(self.source)
        second, _, _ = variants.read_with_thumbnail(self.source, 240)
        self.assertNotEqual(first, second)
        self.assertEqual(
            variants.read_with_thumbnail(self.source, 0)[0], self.source.read_bytes()
        )

    def test_orientation_transparency_and_animation_are_preserved(self):
        oriented = self.root / "oriented.jpg"
        image = Image.new("RGB", (800, 400), "green")
        exif = image.getexif()
        exif[274] = 6
        image.save(oriented, exif=exif)
        body = variants.build_thumbnail(oriented, 160)
        with Image.open(io.BytesIO(body)) as result:
            self.assertEqual(result.size, (160, 320))
        transparent = self.root / "alpha.png"
        Image.new("RGBA", (400, 300), (255, 0, 0, 80)).save(transparent)
        with Image.open(
            io.BytesIO(variants.build_thumbnail(transparent, 96))
        ) as result:
            self.assertIn("A", result.getbands())
            self.assertEqual(result.getpixel((0, 0))[3], 80)
        animated = self.root / "animated.gif"
        Image.new("RGB", (200, 200), "red").save(
            animated,
            save_all=True,
            append_images=[Image.new("RGB", (200, 200), "blue")],
            duration=100,
            loop=0,
        )
        self.assertEqual(
            variants.read_with_thumbnail(animated, 48)[0], animated.read_bytes()
        )

    def test_cross_process_requests_share_one_atomic_derivative(self):
        marker = self.root / "encodes.txt"
        code = """
import os,sys
from pathlib import Path
from backend import image_variants as v
original=v.build_thumbnail
def encode(*args):
    with Path(sys.argv[2]).open('a') as log:log.write('encode\\n')
    return original(*args)
v.build_thumbnail=encode
data,kind,ok=v.read_with_thumbnail(Path(sys.argv[1]),640)
assert ok and kind=='image/webp'
print(v.cache_key(Path(sys.argv[1]),640))
"""

        def run(seed):
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-c",
                    code,
                    str(self.source),
                    str(marker),
                ],
                env={**os.environ, "PYTHONHASHSEED": str(seed)},
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            keys = list(executor.map(run, (1, 2, 3)))
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(marker.read_text().splitlines(), ["encode"])
        self.assertEqual(list(self.cache.glob("*.tmp")), [])

    def test_cache_budget_prunes_only_derivatives_and_bad_source_falls_back(self):
        self.cache.mkdir()
        old = self.cache / ("0" * 64 + ".webp")
        old.write_bytes(b"x" * 1100000)
        os.utime(old, (1, 1))
        original = self.cache / "original.webp"
        original.write_bytes(b'original source')
        os.utime(original, (1, 1))
        with patch.dict(os.environ, {"HANDRAW_IMAGE_CACHE_MAX_BYTES": "1048576"}):
            variants._last_prune.clear()
            variants.prune_cache(self.cache)
        self.assertFalse(old.exists())
        self.assertEqual(original.read_bytes(), b'original source')
        self.assertTrue(self.source.exists())
        broken = self.root / "bad.jpg"
        broken.write_bytes(b"not an image")
        self.assertEqual(
            variants.read_with_thumbnail(broken, 48),
            (b"not an image", "image/jpeg", False),
        )
