"""#11 Web 537 / actual Skill main v1.9.11 540 parity witness; all Skill-only candidates unapproved.

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
        self.assertFalse({"FF-018", "FF-019", "FG-025"} &
                         {r["id"] for r in approved},
                         "unapproved proposals must not be copied to Web")

    def test_proposals_are_explicitly_unapproved_and_hashed(self):
        pending = read(ROOT / "ops/official_catalog_pending_11.json")
        proposals = {r["code"]: r for r in pending["pendingSkillOnly"]}
        self.assertEqual(set(proposals), {"FF-018", "FF-019", "FG-025"})
        self.assertEqual({r["kind"] for r in proposals.values()}, {"style"})
        self.assertTrue(all(
            r.get("state") == "awaiting_website_editorial_review"
            and r.get("issue") in (11, 132) and len(r["sha256"]) == 64
            for r in proposals.values()))
        self.assertEqual(proposals["FF-019"]["issue"], 132)
        self.assertEqual(proposals["FF-019"]["name"], "Hyperreal 3D Cartoon Portrait")
        self.assertEqual(proposals["FF-019"]["sha256"],
                         "fc4f512c237ce56a6cf43776912be12ba9e81fc21f575ef962752e7302329fd3")

    @unittest.skipUnless(SKILL_ROOT, "real Skill main checkout present in PG/S3 CI job only")
    def test_actual_skill_main_540_and_strict_release_blocked(self):
        skill = Path(SKILL_ROOT)
        report = audit(
            read(ROOT / "plugin/content/catalog.json"),
            read(skill / "references/styles.json"),
            read(skill / "references/layouts.json"),
            read(ROOT / "ops/official_catalog_pending_11.json"),
        )
        self.assertEqual(report["webStaticCount"], 537)
        self.assertEqual(report["webCount"], 537)
        self.assertEqual(report["skillCount"], 540)
        self.assertEqual(report["knownPending"], ["FF-018", "FF-019", "FG-025"])
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
