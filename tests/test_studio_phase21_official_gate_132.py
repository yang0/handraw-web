"""Phase21: signed, human-scoped website->Skill strict parity never grants GO."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from ops.studio_official_approval_132 import CODES, sha, canon
from ops.studio_phase21_official_gate_132 import evaluate_chain,main

WEB="a"*40
NOW=datetime(2026,11,10,tzinfo=timezone.utc)
NAMES=("Low Poly Art","Hyperreal 3D Cartoon Portrait","Perler Bead Pixel Art")


def fixture():
    sk=[{"number":"FA-001","generation_name":"Existing Style"}]
    layouts=[{"id":"IG-001","name":"Existing Layout"}]
    cat={"resources":[{"id":"FA-001","kind":"style","name":"Existing Style"},
                      {"id":"IG-001","kind":"layout","name":"Existing Layout"}]}
    db=[]
    pending=[]
    rights=[]
    approvals=[]
    keys=[]
    for role,kid in (("website_editor","editor-p21"),
                     ("independent_reviewer","reviewer-p21")):
        priv=Ed25519PrivateKey.generate()
        pub=priv.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        keys.append((role,kid,priv,base64.b64encode(pub).decode("ascii")))
    reg={"schemaVersion":1,"issuer":"handraw-website-ops",
         "keys":[{"role":role,"keyId":kid,"publicKeyBase64":pub}
                 for role,kid,_,pub in keys]}
    for i,(code,name) in enumerate(zip(CODES,NAMES),start=1):
        row={"number":code,"generation_name":name,"traits":f"CI-fixture-{i}"}
        dbrow={"number":code,"generation_name":name,"websiteStatus":"published"}
        sk.append(row)
        db.append(dbrow)
        pending.append({"code":code,"kind":"style","name":name,
                        "state":"awaiting_website_editorial_review",
                        "sha256":sha(row),"issue":132,"reason":"mock-test"})
        rightsrow={"candidateCode":code,"skillSourceSha256":sha(row),
             "rightsReviewEvidenceId":f"mock-rights-{i}",
             "promptProvenanceEvidenceId":f"prompt-{i}",
             "descriptionProvenanceEvidenceId":f"description-{i}",
             "reviewDecision":"cleared_for_editorial_signature",
             "assets":[{"assetSha256":format(i,"064x"),
               "originType":"explicit-license",
               "rightsHolderEvidenceId":f"author-{i}",
               "licenseOrPermissionEvidenceId":f"license-{i}",
               "attributionEvidenceId":f"credit-{i}",
               "commercialReuseAllowed":True,"derivativeUseAllowed":True,
               "officialWebsitePublishAllowed":True}]}
        rights.append(rightsrow)
        payload={"schemaVersion":1,"candidateCode":code,
             "skillSourceSha256":sha(row),
             "webDbPublishedRowSha256":sha(dbrow),
             "deployedSha":WEB,
             "websiteActionId":f"web-action-{i}",
             "rightsReviewEvidenceId":rightsrow["rightsReviewEvidenceId"],
             "rightsReviewEvidenceSha256":sha(rightsrow),
             "reviewedAtUtc":"2026-11-09T23:00:00Z",
             "result":"website_published_and_reviewed"}
        approvals.append({"payload":payload,
             "signatures":[{"role":role,"keyId":kid,
                "signatureBase64":base64.b64encode(
                     priv.sign(canon(payload))).decode("ascii")}
                for role,kid,priv,_ in keys]})
    src={"schemaVersion":1,"sourceSystem":"website-postgresql-read-only",
         "sourceRole":"readonly-export","webDeployedSha":WEB,
         "publishedStylesSha256":sha(db),"publishedLayoutsSha256":sha([]),
         "operatorId":"db-export-operator","independentReviewerId":"db-export-reviewer",
         "exportSessionId":"mock-export-21"}
    return {
        "catalog":cat,"skill_styles":sk,"skill_layouts":layouts,
        "pending_before":{"schemaVersion":1,"pendingSkillOnly":pending},
        "pending_after":{"schemaVersion":1,"pendingSkillOnly":[]},
        "published_styles":db,"published_layouts":[],
        "approvals":{"schemaVersion":1,"approvals":approvals},
        "rights_reviews":{"schemaVersion":1,"reviews":rights},
        "trust_registry":reg,"trust_sha":sha(reg),
        "deployed_sha":WEB,"source_receipt":src,"now":NOW,
    }


class Phase21OfficialChain(unittest.TestCase):
    def test_signature_first_full_dry_run_never_grants_release(self):
        case=fixture()
        out=evaluate_chain(**case)
        self.assertEqual(out["signedCandidateClaims"],3)
        self.assertTrue(out["strictParityDryRunPassed"])
        self.assertEqual(out["stage"],"SIGNED_AND_STRICTLY_STAGED_FOR_INDEPENDENT_REVIEW")
        for name in ("automaticPromotionAuthorized",
                     "officialWebsitePublicationMade","skillPublicationMade",
                     "rightsOwnershipIndependentlyProven",
                     "websiteDbOriginIndependentlyProven"):
            self.assertFalse(out[name],name)
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("mock-rights",json.dumps(out))

    def test_no_signed_evidence_fail_closed_even_with_matching_fake_db(self):
        case=fixture()
        case["approvals"]=None
        out=evaluate_chain(**case)
        self.assertEqual(out["stage"],"MISSING_WEBSITE_APPROVAL")
        self.assertEqual(out["signedCandidateClaims"],0)
        self.assertFalse(out["strictParityDryRunPassed"])

    def test_partial_bundle_is_not_complete(self):
        case=fixture()
        case["approvals"]["approvals"].pop()
        out=evaluate_chain(**case)
        self.assertEqual(out["signedCandidateClaims"],2)
        self.assertEqual(out["stage"],"INCOMPLETE_TWO_ROLE_SIGNATURES")

    def test_tampering_approval_metadata_or_signer_is_rejected(self):
        for field,new in (("websiteActionId","replayed-action"),
                          ("webDbPublishedRowSha256","0"*64),
                          ("rightsReviewEvidenceSha256","0"*64),
                          ("deployedSha","b"*40)):
            case=fixture()
            case["approvals"]["approvals"][0]["payload"][field]=new
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate_chain(**case)
        case=fixture()
        case["trust_sha"]="f"*64
        with self.assertRaises(ValueError):
            evaluate_chain(**case)

    def test_db_origin_fingerprint_role_and_operator_reviewer_independent(self):
        for field,new in (("webDeployedSha","b"*40),
                          ("sourceSystem","moto-or-self-claimed-ci"),
                          ("sourceRole","writer"),
                          ("publishedStylesSha256","f"*64),
                          ("publishedLayoutsSha256","f"*64),
                          ("independentReviewerId","db-export-operator")):
            case=fixture()
            case["source_receipt"][field]=new
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate_chain(**case)
        case=fixture()
        case["source_receipt"]=None
        with self.assertRaises(ValueError):
            evaluate_chain(**case)

    def test_no_silent_resource_rollback_missing_skill_and_stale_pending(self):
        case=fixture()
        case["skill_styles"][1]["traits"]="same-name-new-content"
        with self.assertRaises(ValueError):
            evaluate_chain(**case)
        case=fixture()
        case["pending_after"]=deepcopy(case["pending_before"])
        with self.assertRaises(ValueError):
            evaluate_chain(**case)
        case=fixture()
        case["skill_styles"].pop()
        with self.assertRaises(ValueError):
            evaluate_chain(**case)

    def test_cli_without_review_returns_restricted_no_go_not_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"phase21.json"
            args=["--deployed-sha",WEB,"--report",str(path)]
            self.assertEqual(main(args),0)
            self.assertEqual(json.loads(path.read_text())["decision"],"NO-GO")
            self.assertEqual(main(args),2)


if __name__=="__main__":
    unittest.main()
