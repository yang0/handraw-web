"""#11 frozen 2026-11-09 Web 537 / actual Skill main 539 parity witness.

This deliberately tests the REAL Skill main catalog in the dedicated CI job,
not the independently SHA-pinned executable Skill client. A changed main
catalog requires a new human-reviewed snapshot; never auto-import proposals.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from ops.check_official_catalog_parity import audit

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = os.environ.get("HANDRAW_SKILL_CATALOG_ROOT", "")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Snapshot11(unittest.TestCase):
    def test_web_catalog_has_537_approved_static_entries(self):
        catalog = read(ROOT / "plugin/content/catalog.json")
        approved = [r for r in catalog["resources"]
                    if r.get("kind") in ("style", "layout")]
        self.assertEqual(len([r for r in approved if r["kind"] == "style"]), 367)
        self.assertEqual(len([r for r in approved if r["kind"] == "layout"]), 170)
        self.assertEqual(len(approved), 537)
        self.assertEqual(len({r["id"] for r in approved}), 537)
        self.assertFalse({"FF-018", "FG-025"} &
                         {r["id"] for r in approved},
                         "unapproved proposals must not be copied to Web")

    def test_proposals_are_explicitly_unapproved_and_hashed(self):
        pending = read(ROOT / "ops/official_catalog_pending_11.json")
        proposals = {r["code"]: r for r in pending["pendingSkillOnly"]}
        self.assertEqual(set(proposals), {"FF-018", "FG-025"})
        self.assertEqual({r["kind"] for r in proposals.values()}, {"style"})
        self.assertTrue(all(
            r.get("state") == "awaiting_website_editorial_review"
            and r.get("issue") == 11 and len(r["sha256"]) == 64
            for r in proposals.values()))

    @unittest.skipUnless(SKILL_ROOT, "real Skill main checkout present in PG/S3 CI job only")
    def test_actual_skill_main_539_and_strict_release_blocked(self):
        skill = Path(SKILL_ROOT)
        report = audit(
            read(ROOT / "plugin/content/catalog.json"),
            read(skill / "references/styles.json"),
            read(skill / "references/layouts.json"),
            read(ROOT / "ops/official_catalog_pending_11.json"),
        )
        self.assertEqual(report["webStaticCount"], 537)
        self.assertEqual(report["webCount"], 537)
        self.assertEqual(report["skillCount"], 539)
        self.assertEqual(report["knownPending"], ["FF-018", "FG-025"])
        for key in ("unexpectedSkillOnly", "webOnly", "alteredPending",
                    "mismatchedName", "mismatchedKind", "staleExceptions"):
            self.assertEqual(report[key], [], key)
        self.assertTrue(report["dbAuditRequired"])
        self.assertFalse(report["readyForRelease"])
        with self.assertRaises(ValueError,
                               msg="--strict must reject pending editorial review and missing DB export"):
            audit(
                read(ROOT / "plugin/content/catalog.json"),
                read(skill / "references/styles.json"),
                read(skill / "references/layouts.json"),
                read(ROOT / "ops/official_catalog_pending_11.json"),
                strict=True,
            )


if __name__ == "__main__":
    unittest.main()
