"""Unit & integration tests for Issue #55: Related works thumbnail dimensions and aspect ratio enrichment."""
from __future__ import annotations

import unittest
from pathlib import Path

from backend import curation as C, forum_resources as R, services as S
from tests import test_v2_curation as fixtures


class RelatedThumbNoCropTests(unittest.TestCase):
    setUp = fixtures.CurationTests.setUp
    tearDown = fixtures.CurationTests.tearDown
    item = fixtures.CurationTests.item

    def test_related_works_feed_enriches_aspect_ratio_and_first_image(self) -> None:
        # 1. Publish a portrait work (3:4) using style FA-013
        work_portrait = S.publish_user_work(
            self.db,
            self.author,
            {
                "title": "竖版手绘人像",
                "prompt": "暖纸水墨肖像",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styles": ["FA-013"],
                "ratio": "3:4",
                "price": 0,
            },
        )
        self.assertTrue(work_portrait.get("ok"))

        # 2. Publish a landscape work (16:9) with multiple images using style FA-013
        work_landscape = S.publish_user_work(
            self.db,
            self.author,
            {
                "title": "横版连作长卷",
                "prompt": "连环水墨图册",
                "images": [
                    "/images/poster-demo-autumn-equinox.webp",
                    "/images/individual/FA/FA-013.webp",
                ],
                "styles": ["FA-013"],
                "ratio": "16:9",
                "price": 0,
            },
        )
        self.assertTrue(work_landscape.get("ok"))

        # 3. Query related works via related_items
        res = R.related_items(self.db, None, "style", "FA-013", "works")
        self.assertTrue(res.get("ok"))
        items = res.get("items", [])
        self.assertGreaterEqual(len(items), 2)

        # 4. Check portrait item
        port_item = next(it for it in items if it["id"] == work_portrait["workId"])
        self.assertIn("aspectRatio", port_item)
        self.assertGreater(port_item["aspectRatio"], 0)
        self.assertIn("coverWidth", port_item)
        self.assertIn("coverHeight", port_item)
        self.assertEqual(port_item["image"], "/images/individual/FA/FA-013.webp")

        # 5. Check landscape multi-image item: must take first image
        land_item = next(it for it in items if it["id"] == work_landscape["workId"])
        self.assertIn("aspectRatio", land_item)
        self.assertGreater(land_item["aspectRatio"], 0)
        # Multi-image: image must be first image
        self.assertEqual(land_item["image"], "/images/poster-demo-autumn-equinox.webp")
        self.assertEqual(land_item["images"][0], "/images/poster-demo-autumn-equinox.webp")

    def test_resource_detail_relations_contains_aspect_ratio(self) -> None:
        # Publish a work with style FA-013
        S.publish_user_work(
            self.db,
            self.author,
            {
                "title": "画风关联作品",
                "prompt": "提示词",
                "images": ["/images/individual/FA/FA-013.webp"],
                "styles": ["FA-013"],
                "ratio": "3:4",
                "price": 0,
            },
        )
        detail = R.resource_detail(self.db, None, "style", "FA-013")
        self.assertTrue(detail.get("ok"))
        relations = detail.get("relations", [])
        work_rel = next((r for r in relations if r["tab"] == "works"), None)
        self.assertIsNotNone(work_rel)
        work_items = work_rel.get("items", [])
        self.assertGreaterEqual(len(work_items), 1)
        self.assertIn("aspectRatio", work_items[0])
        self.assertGreater(work_items[0]["aspectRatio"], 0)


if __name__ == "__main__":
    unittest.main()
