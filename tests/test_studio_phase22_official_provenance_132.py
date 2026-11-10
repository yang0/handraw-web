"""Phase22 raw Web PG source -> Skill SHA -> Phase21 Ed25519 chain negatives."""
from __future__ import annotations

from copy import deepcopy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from ops.studio_phase21_official_web_export_132 import transform,build_receipt
from ops.studio_phase22_official_provenance_132 import evaluate,check_skill_checkout,load_pinned_skill_sources,main

WEB="a"*40
SKILL="b"*40


def source_rows():
    return [{"code":"FF-018","kind":"style","name":"Low Poly Art",
         "group_name":"FI","description":"Licensed test",
         "definition":"mock","unlock_cost":0,
         "source_type":"official","status":"published"},
        {"code":"FF-019","kind":"style","name":"Hyperreal 3D Cartoon Portrait",
         "group_name":"FI","description":"Licensed test",
         "definition":"mock","unlock_cost":0,
         "source_type":"official","status":"published"},
        {"code":"FG-025","kind":"style","name":"Perler Bead Pixel Art",
         "group_name":"FI","description":"Licensed test",
         "definition":"mock","unlock_cost":0,
         "source_type":"official","status":"published"}]


def params():
    raw=source_rows()
    styles,layouts,digest=transform(raw)
    receipt=build_receipt(styles=styles,layouts=layouts,
        raw_digest=digest,deployed_sha=WEB,operator="qa-operator",
        reviewer="qa-independent",session="mock-phase22")
    return dict(raw_web_rows=raw,published_styles=styles,published_layouts=layouts,
        source_receipt=receipt,skill_checkout_sha=SKILL,expected_skill_sha=SKILL,
        catalog={},skill_styles=[],skill_layouts=[],pending_before={},
        pending_after={},approvals={},rights_reviews={},
        trust_registry={},trust_sha="f"*64,deployed_sha=WEB)


class Proc:
    def __init__(self,stdout):self.stdout=stdout;self.returncode=0


class Phase22OfficialTest(unittest.TestCase):
    @patch("ops.studio_phase22_official_provenance_132.evaluate_chain",
           return_value={"signedCandidateClaims":3,
             "stage":"SIGNED_AND_STRICTLY_STAGED_FOR_INDEPENDENT_REVIEW",
             "strictParityDryRunPassed":True})
    def test_raw_export_hashes_bind_signatures_but_never_grant_go(self,chain):
        out=evaluate(**params())
        chain.assert_called_once()
        self.assertTrue(out["rawWebsiteRowsMatchReadOnlyExport"])
        self.assertEqual(out["phase21SignedCandidateClaims"],3)
        self.assertFalse(out["websiteLiveDatabaseOriginIndependentlyAuthenticated"])
        self.assertFalse(out["actualCommercialRightsIndependentlyAuthenticated"])
        self.assertFalse(out["websitePromotionAuthorized"])
        self.assertFalse(out["skillMainMutated"])
        self.assertEqual(out["decision"],"NO-GO")

    @patch("ops.studio_phase22_official_provenance_132.evaluate_chain")
    def test_mutated_web_db_or_skill_sha_rejected_before_signatures(self,chain):
        for field in ("name","definition","status"):
            kw=params()
            kw["raw_web_rows"][0][field]="tampered"
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(**kw)
        kw=params()
        kw["source_receipt"]["sourceRowsSha256"]="0"*64
        with self.assertRaises(ValueError):evaluate(**kw)
        kw=params()
        kw["skill_checkout_sha"]="c"*40
        with self.assertRaises(ValueError):evaluate(**kw)
        chain.assert_not_called()

    def test_checkout_full_sha_and_clean_worktree_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/".git").mkdir()
            def clean(args,**kwargs):
                return Proc(SKILL+"\n" if args[-3:]==["rev-parse","--verify","HEAD"] else "")
            observed=check_skill_checkout(root,SKILL,runner=clean)
            self.assertTrue(observed["checkoutClean"])
            with self.assertRaises(ValueError):
                check_skill_checkout(root,"short",runner=clean)
            def dirty(args,**kwargs):
                return Proc(SKILL+"\n" if args[-3:]==["rev-parse","--verify","HEAD"] else " M styles.json")
            with self.assertRaises(ValueError):
                check_skill_checkout(root,SKILL,runner=dirty)
            with self.assertRaises(ValueError):
                check_skill_checkout(root,"c"*40,runner=clean)

    @unittest.skipUnless(shutil.which("git"), "Git CLI required for pinned blob test")
    def test_cli_skill_inputs_are_actual_tracked_blobs_not_external_json(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"skill"
            refs=root/"skills"/"handdraw-style-prompter"/"references"
            refs.mkdir(parents=True)
            styles=refs/"styles.json"
            layouts=refs/"layouts.json"
            styles.write_text(json.dumps([{"number":"FF-018"}]),encoding="utf-8")
            layouts.write_text(json.dumps([{"number":"IG-001"}]),encoding="utf-8")
            def git(*args):
                proc=subprocess.run(["git","-C",str(root),*args],
                    check=True,capture_output=True,text=True,timeout=10)
                return proc.stdout.strip()
            git("init","-q")
            git("add","skills/handdraw-style-prompter/references/styles.json",
                "skills/handdraw-style-prompter/references/layouts.json")
            git("-c","user.name=CI","-c","user.email=ci@example.invalid",
                "-c","commit.gpgsign=false","commit","-qm","pinned fixture")
            sha=git("rev-parse","HEAD")
            bound,pinned_styles,pinned_layouts=load_pinned_skill_sources(
                root,sha,styles,layouts)
            self.assertEqual(bound["pinnedSkillSha"],sha)
            self.assertEqual(pinned_styles,[{"number":"FF-018"}])
            self.assertEqual(pinned_layouts,[{"number":"IG-001"}])

            outside=Path(td)/"forged-styles.json"
            outside.write_text(styles.read_text(encoding="utf-8"),encoding="utf-8")
            # Even semantically identical content outside the checkout is not
            # authoritative; Git SHA and a clean worktree alone are not enough.
            with self.assertRaises(ValueError):
                load_pinned_skill_sources(root,sha,outside,layouts)
            with self.assertRaises(ValueError):
                load_pinned_skill_sources(root,"f"*40,styles,layouts)

            layouts.write_text("[]",encoding="utf-8")
            with self.assertRaises(ValueError):
                load_pinned_skill_sources(root,sha,styles,layouts)
            git("restore","skills/handdraw-style-prompter/references/layouts.json")
            if hasattr(Path,"symlink_to"):
                links=Path(td)/"linked-styles.json"
                try:
                    links.symlink_to(styles)
                except (OSError,NotImplementedError):
                    pass
                else:
                    with self.assertRaises(ValueError):
                        load_pinned_skill_sources(root,sha,links,layouts)

    def test_official_cli_missing_private_approval_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"report.json"
            self.assertEqual(main(["--raw-web-rows",str(Path(td)/"missing.json"),
                "--skill-checkout",td,"--skill-sha",SKILL,
                "--catalog","plugin/content/catalog.json",
                "--skill-styles","missing","--skill-layouts","missing",
                "--pending-before","missing","--pending-after","missing",
                "--published-styles","missing","--published-layouts","missing",
                "--approvals","missing","--rights","missing",
                "--trust-registry","missing","--source-receipt","missing",
                "--deployed-sha",WEB,"--report",str(path)]),2)
            self.assertFalse(path.exists())


if __name__=="__main__":
    unittest.main()
