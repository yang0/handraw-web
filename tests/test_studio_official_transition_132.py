"""#132 staged approval is a pure dry run and never publishes any resource."""
from __future__ import annotations

from copy import deepcopy
import json
import unittest

from ops.check_official_catalog_parity import audit
from ops.studio_official_approval_132 import CODES, sha
from ops.studio_official_transition_132 import stage_transition

WEB = "a"*40
NAMES = ("Low Poly Art", "Hyperreal 3D Cartoon Portrait", "Perler Bead Pixel Art")


def sample():
    catalog={"resources":[{"id":"FA-001","kind":"style","name":"Existing Style"},
                          {"id":"IG-001","kind":"layout","name":"Existing Layout"}]}
    styles=[{"number":"FA-001","generation_name":"Existing Style"}]
    layouts=[{"id":"IG-001","name":"Existing Layout"}]
    db=[]
    pending=[]
    signed=[]
    for i,(code,name) in enumerate(zip(CODES,NAMES),start=1):
        skill={"number":code,"generation_name":name,"style_prompt":f"candidate-{i}"}
        row={"number":code,"generation_name":name,"rights_status":"human-review-fixture"}
        styles.append(skill)
        db.append(row)
        pending.append({"code":code,"kind":"style","name":name,
                        "sha256":sha(skill),"state":"awaiting_website_editorial_review",
                        "issue":132,"reason":"offline-test-only"})
        signed.append({"candidateCode":code,"deployedSha":WEB,
                       "skillSourceSha256":sha(skill),
                       "webDbPublishedRowSha256":sha(row),
                       "result":"website_published_and_reviewed"})
    old={"schemaVersion":1,"pendingSkillOnly":pending}
    future={"schemaVersion":1,"pendingSkillOnly":[]}
    return [catalog,styles,layouts,old,future,db,[],signed]


def stage(case,sha_=WEB):
    return stage_transition(*case,deployed_sha=sha_)


class OfficialTransitionTest(unittest.TestCase):
    def test_preapproval_strict_blocked_even_with_proposed_web_rows(self):
        c=sample()
        with self.assertRaises(ValueError):
            audit(c[0],c[1],c[2],c[3],strict=True,
                  approved_styles=c[5],approved_layouts=c[6])

    def test_postapproval_dry_run_exact_three_still_no_go(self):
        out=stage(sample())
        self.assertTrue(out["allStagedFingerprintChecksPassed"])
        self.assertTrue(out["strictCatalogParityDryRunPassed"])
        self.assertEqual(out["stagedCodes"],list(CODES))
        self.assertFalse(out["signedPayloadSignaturesVerifiedHere"])
        self.assertFalse(out["liveWebsiteDbOriginVerifiedHere"])
        self.assertFalse(out["publishingAttempted"])
        self.assertFalse(out["productionApprovalAuthorized"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("candidate-1",json.dumps(out))

    def test_old_pending_manifest_cannot_be_reused_after_promotion(self):
        c=sample()
        c[4]=deepcopy(c[3])
        with self.assertRaises(ValueError):
            stage(c)

    def test_renamed_or_silently_mutated_skill_metadata_blocks_rollback(self):
        for field,new_value in (
            ("style_prompt","same-name-different-prompt"),
            ("generation_name","Different Display Name"),
        ):
            c=sample()
            c[1][1][field]=new_value
            with self.subTest(field=field),self.assertRaises(ValueError):
                stage(c)
        c=sample()
        c[1].pop(1)
        with self.assertRaises(ValueError):
            stage(c)

    def test_replayed_or_mutated_approved_db_row_blocks_release(self):
        for field,new_value in (
            ("generation_name","Different Display Name"),
            ("rights_status","permission-revoked"),
        ):
            c=sample()
            c[5][0][field]=new_value
            with self.subTest(field=field),self.assertRaises(ValueError):
                stage(c)
        c=sample()
        c[5].pop(0)
        with self.assertRaises(ValueError):
            stage(c)
        c=sample()
        c[5].append(deepcopy(c[5][0]))
        with self.assertRaises(ValueError):
            stage(c)

    def test_missing_one_or_duplicate_action_and_wrong_deployed_sha_are_rejected(self):
        c=sample()
        c[7][1]["candidateCode"]=c[7][0]["candidateCode"]
        with self.assertRaises(ValueError):
            stage(c)
        c=sample()
        c[7][0]["deployedSha"]="b"*40
        with self.assertRaises(ValueError):
            stage(c)
        c=sample()
        c[7].pop()
        with self.assertRaises(ValueError):
            stage(c)
        c=sample()
        with self.assertRaises(ValueError):
            stage(c,sha_="b"*40)

    def test_existing_approved_style_or_layout_cannot_disappear(self):
        c=sample()
        c[1].pop(0)
        with self.assertRaises(ValueError):
            stage(c)
        c=sample()
        c[2]=[]
        with self.assertRaises(ValueError):
            stage(c)


if __name__=="__main__":
    unittest.main()
