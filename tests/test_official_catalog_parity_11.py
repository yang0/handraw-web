"""#11 official ID authority drift regression: no unapproved Skill -> Web promotion.

Pure fixtures exercise the audit; the existing production-storage CI job
executes the same checker against the *pinned real Skill checkout*.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ops.check_official_catalog_parity import _sha, audit, main


class OfficialCatalogParity11(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = {"resources": [
            {"id": "FA-001", "kind": "style", "name": "已发布画风"},
            {"id": "IG-001", "kind": "layout", "name": "已发布图型"},
            {"id": "C-01", "kind": "color", "name": "非本次比对类型"},
        ]}
        self.pending_style = {
            "number": "FG-025", "generation_name": "Perler Bead Pixel Art",
            "traits": "原创拼豆颗粒", "reference": "拼豆像素画",
        }
        self.styles = [
            {"number": "FA-001", "generation_name": "已发布画风"},
            self.pending_style.copy(),
        ]
        self.layouts = [{"id": "IG-001", "name": "已发布图型"}]
        self.pending = {"schemaVersion": 1, "pendingSkillOnly": [{
            "code": "FG-025", "kind": "style",
            "name": "Perler Bead Pixel Art",
            "sha256": _sha(self.pending_style),
            "issue": 11,
            "reason": "Not yet approved by website",
        }]}

    def check(self, strict: bool = False, *, with_db: bool = False,
              dynamic_styles=None, dynamic_layouts=None):
        return audit(self.catalog, self.styles, self.layouts,
                     self.pending, strict=strict,
                     approved_styles=(dynamic_styles if dynamic_styles is not None else [])
                        if with_db else None,
                     approved_layouts=(dynamic_layouts if dynamic_layouts is not None else [])
                        if with_db else None)

    def test_known_unapproved_skill_only_code_is_visible_but_not_released(self):
        report = self.check()
        self.assertEqual(report["webCount"], 2)
        self.assertEqual(report["skillCount"], 3)
        self.assertEqual(report["webOnly"], [])
        self.assertEqual(report["skillOnly"], ["FG-025"])
        self.assertEqual(report["knownPending"], ["FG-025"])
        self.assertEqual(report["status"], "pending_review")
        self.assertFalse(report["readyForRelease"])
        # Even an acknowledged candidate must block production parity signoff.
        with self.assertRaisesRegex(ValueError, "FG-025"):
            self.check(strict=True)

    def test_full_website_authorization_allows_strict_only_after_removing_exception(self):
        self.catalog["resources"].append({
            "id": "FG-025", "kind": "style", "name": "Perler Bead Pixel Art"})
        # A stale exception cannot quietly survive a review/publication.
        with self.assertRaisesRegex(ValueError, "staleExceptions"):
            self.check()
        self.pending["pendingSkillOnly"] = []
        # Static parity is not sufficient for a production release gate:
        # the Web DB may contain newly published official records as well.
        with self.assertRaisesRegex(ValueError, "dbAuditRequired"):
            self.check(strict=True)
        result = self.check(strict=True, with_db=True)
        self.assertEqual(result["status"], "in_sync")
        self.assertEqual(result["webDynamicApprovedCount"], 0)
        self.assertTrue(result["approvedExportChecked"])
        self.assertTrue(result["readyForRelease"])

    def test_dynamic_official_web_export_detects_unshipped_code(self):
        # A new, approved DB-only official code must NOT silently pass the
        # static catalog.json parity check when it is absent from Skill.
        dynamic = [{"number": "FA-002", "generation_name": "官网新画风"}]
        with self.assertRaisesRegex(ValueError, "FA-002"):
            self.check(with_db=True, dynamic_styles=dynamic)
        self.styles.append({"number": "FA-002", "generation_name": "官网新画风"})
        report = self.check(with_db=True, dynamic_styles=dynamic)
        self.assertEqual(report["webStaticCount"], 2)
        self.assertEqual(report["webDynamicApprovedCount"], 1)
        self.assertEqual(report["knownPending"], ["FG-025"])
        self.assertFalse(report["readyForRelease"])
        self.catalog["resources"].append({
            "id": "FG-025", "kind": "style", "name": "Perler Bead Pixel Art"})
        self.pending["pendingSkillOnly"] = []
        self.assertTrue(self.check(strict=True, with_db=True,
                                   dynamic_styles=dynamic)["readyForRelease"])

    def test_db_approved_export_kind_and_code_collision_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "collision"):
            self.check(with_db=True, dynamic_styles=[{"number": "FA-001"}])
        with self.assertRaisesRegex(ValueError, "collision"):
            self.check(with_db=True,
                       dynamic_styles=[{"number": "FA-002"}],
                       dynamic_layouts=[{"id": "FA-002"}])
        with self.assertRaisesRegex(ValueError, "supplied together"):
            audit(self.catalog, self.styles, self.layouts, self.pending,
                  approved_styles=[])

    def test_static_parity_does_not_auto_claim_release_without_db_evidence(self):
        self.catalog["resources"].append({
            "id": "FG-025", "kind": "style", "name": "Perler Bead Pixel Art"})
        self.pending["pendingSkillOnly"] = []
        report = self.check()
        self.assertEqual(report["status"], "in_sync")
        self.assertFalse(report["approvedExportChecked"])
        self.assertFalse(report["readyForRelease"])

    def test_unapproved_new_style_causes_ci_failure(self):
        self.styles.append({"number": "FG-026", "generation_name": "Unauthorized new entry"})
        with self.assertRaisesRegex(ValueError, "FG-026"):
            self.check()

    def test_unapproved_new_layout_causes_ci_failure(self):
        self.layouts.append({"id": "IG-002", "name": "Unreviewed layout"})
        with self.assertRaisesRegex(ValueError, "IG-002"):
            self.check()

    def test_modified_pending_definition_or_name_causes_ci_failure(self):
        self.styles[1]["traits"] = "Unexpected style mutation"
        with self.assertRaisesRegex(ValueError, "alteredPending"):
            self.check()
        self.styles[1] = self.pending_style.copy()
        self.styles[1]["generation_name"] = "Unexpected renamed proposal"
        with self.assertRaisesRegex(ValueError, "alteredPending"):
            self.check()

    def test_missing_skill_export_or_code_collision_causes_ci_failure(self):
        self.styles.pop(0)  # Previously approved Web style no longer exists in Skill.
        with self.assertRaisesRegex(ValueError, "FA-001"):
            self.check()
        self.styles.insert(0, {"number": "FA-001", "generation_name": "Published"})
        self.styles.append({"number": "FA-001", "generation_name": "Conflicting"})
        with self.assertRaisesRegex(ValueError, "duplicated official ID"):
            self.check()

    def test_same_code_different_kind_fails(self):
        self.catalog["resources"][0]["kind"] = "layout"
        with self.assertRaisesRegex(ValueError, "mismatchedKind"):
            self.check()

    def test_cross_category_collision_fails(self):
        self.layouts.append({"id": "FA-001", "name": "Wrong class"})
        with self.assertRaisesRegex(ValueError, "duplicate Skill code"):
            self.check()

    def test_pending_without_issue_fingerprint_or_reason_is_invalid(self):
        rec = self.pending["pendingSkillOnly"][0]
        for key, value in (("sha256", "bad"), ("issue", 0), ("reason", "")):
            original = rec[key]
            rec[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check()
            rec[key] = original
        self.pending["pendingSkillOnly"].append(rec.copy())
        with self.assertRaisesRegex(ValueError, "duplicate pending"):
            self.check()

    def test_invalid_resource_code_rejected(self):
        self.styles.append({"number": "../FG-026", "name": "Bad ID"})
        with self.assertRaisesRegex(ValueError, "invalid official ID"):
            self.check()

    def test_strict_cli_requires_approved_db_export_files_even_when_static_syncs(self):
        self.catalog["resources"].append({
            "id": "FG-025", "kind": "style", "name": "Perler Bead Pixel Art"})
        self.pending["pendingSkillOnly"] = []
        with tempfile.TemporaryDirectory(prefix="web-db-export-11-") as td:
            root = Path(td)
            skill_root = root / "skill"
            refs = skill_root / "references"
            refs.mkdir(parents=True)
            (refs / "styles.json").write_text(json.dumps(self.styles), encoding="utf-8")
            (refs / "layouts.json").write_text(json.dumps(self.layouts), encoding="utf-8")
            catalog = root / "catalog.json"
            pending = root / "pending.json"
            catalog.write_text(json.dumps(self.catalog), encoding="utf-8")
            pending.write_text(json.dumps(self.pending), encoding="utf-8")
            args = ["--catalog", str(catalog), "--pending", str(pending),
                    "--skill-root", str(skill_root), "--strict"]
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            exported = root / "reviewed-db"
            exported.mkdir()
            (exported / "styles.json").write_text("[]", encoding="utf-8")
            (exported / "layouts.json").write_text("[]", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args + ["--approved-export-dir", str(exported)]), 0)
            (exported / "styles.json").write_text(
                json.dumps([{"number":"FE-099", "generation_name":"网站已发布但未同步"}]),
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args + ["--approved-export-dir", str(exported)]), 2)

    def test_cli_read_only_pending_and_strict_policy(self):
        with tempfile.TemporaryDirectory(prefix="catalog11-") as root:
            root = Path(root)
            skill = root / "skill" / "references"
            skill.mkdir(parents=True)
            web = root / "catalog.json"
            pending = root / "pending.json"
            (skill / "styles.json").write_text(json.dumps(self.styles), encoding="utf-8")
            (skill / "layouts.json").write_text(json.dumps(self.layouts), encoding="utf-8")
            web.write_text(json.dumps(self.catalog), encoding="utf-8")
            pending.write_text(json.dumps(self.pending), encoding="utf-8")
            before = (web.read_bytes(), pending.read_bytes(),
                      (skill / "styles.json").read_bytes())
            stdout, stderr = io.StringIO(), io.StringIO()
            args = ["--catalog", str(web), "--skill-root", str(skill.parent),
                    "--pending", str(pending), "--report", str(root / "audit.json")]
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(args), 0)
            result = json.loads((root / "audit.json").read_text(encoding="utf-8"))
            self.assertFalse(result["readyForRelease"])
            self.assertIn("FG-025", stderr.getvalue())
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(args + ["--strict"]), 2)
            self.assertEqual(before, (web.read_bytes(), pending.read_bytes(),
                                      (skill / "styles.json").read_bytes()))


if __name__ == "__main__":
    unittest.main()
