"""Starter library seed: real works, real style images, honest counters."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import server
from backend.services import build_boot_payload
from ops import seed_starter_library

# The style art is a deployment asset (gitignored, ~47 MB) copied from the
# handraw-style package, so a clean checkout has none.  The seed tests only make
# sense where those images are present.
_STYLE_ART = Path(__file__).resolve().parent.parent / "images" / "individual"
_HAS_ART = _STYLE_ART.is_dir() and any(_STYLE_ART.rglob("*.webp"))


@unittest.skipUnless(_HAS_ART, "style art not installed in this checkout")
class StarterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "starter.db")

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_plan_uses_generated_illustrations_and_known_resources(self):
        plan = seed_starter_library.build_plan(self.db)
        self.assertGreater(len(plan["works"]), 0)
        for work in plan["works"]:
            image = work["images"][0]
            # Each work points at an illustration generated for it, not at a
            # style-gallery cover, so title, prompt and picture agree.
            self.assertTrue(image.startswith("/starter/"), image)
            stem = image.rsplit("/", 1)[-1].removesuffix(".webp")
            shipped = Path(__file__).resolve().parent.parent / "demo" / "starter" / f"{stem}.webp"
            self.assertTrue(shipped.is_file(), f"missing illustration {shipped}")
            self.assertEqual(plan["skipped"], [], "every starter work must resolve")

    def test_apply_creates_published_works_with_zero_counters(self):
        plan = seed_starter_library.build_plan(self.db)
        result = seed_starter_library.apply_plan(self.db, plan)
        self.assertEqual(result["works"], len(plan["works"]))

        boot = build_boot_payload(self.db, None)
        self.assertEqual(len(boot["works"]), len(plan["works"]))

        for work in boot["works"]:
            self.assertEqual(work["likes"], 0, "a seeded work must not start with fake likes")
            self.assertEqual(work["favorites"], 0)
            self.assertEqual(work["cheers"], 0)
            self.assertEqual(work["forks"], 0)
            self.assertTrue(work["styles"], "each starter work references a real style")
            self.assertTrue(
                work["images"][0].startswith("/starter/"),
                "a seeded work shows its own generated illustration",
            )

        showcase = [t for t in boot["topics"] if t.get("category") == "showcase"]
        self.assertEqual(len(showcase), len(plan["works"]), "every work topic lands in 晒作品")
        for topic in showcase:
            self.assertTrue(topic.get("workId"), "a work topic must expose its work id")

    def test_seeding_twice_does_not_duplicate(self):
        plan = seed_starter_library.build_plan(self.db)
        seed_starter_library.apply_plan(self.db, plan)
        # A second run reuses existing accounts and the same requestIds.
        result = seed_starter_library.apply_plan(self.db, plan)
        self.assertEqual(result["users"], 0, "accounts are not recreated")
        count = int(self.db.get_conn().execute("SELECT COUNT(*) FROM works").fetchone()[0])
        self.assertEqual(count, len(plan["works"]), "idempotent seeding must not duplicate works")


if __name__ == "__main__":
    unittest.main()
