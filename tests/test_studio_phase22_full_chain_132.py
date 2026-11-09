"""#132 Phase22 full-chain fixtures: synthetic signatures never imply genuine authorization."""
from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from ops.studio_official_approval_132 import sha,canon
from ops.studio_phase22_full_chain_132 import evaluate_all,main,OFFICIAL_KEYS
from test_studio_phase21_official_gate_132 import fixture as official_fixture
from test_studio_phase22_release_join_132 import sample
from test_studio_phase22_field_matrix_132 import provider_sample,WEB,SKILL,NOW


def bundle():
    master,critical,records=sample()
    official=official_fixture()
    official={k:v for k,v in official.items() if k in OFFICIAL_KEYS}
    p,h=provider_sample()
    source={
        "official_web_export":sha(official["source_receipt"]),
        "skill_checkout":sha({"styles":official["skill_styles"],
             "layouts":official["skill_layouts"],"expectedGitSha":SKILL}),
        **{kind:sha(records[kind]) for kind in records},
    }
    signers=[]
    for role,kid in (("field_operator","fixture-field-operator"),
                     ("independent_reviewer","fixture-independent-auditor")):
        private=Ed25519PrivateKey.generate()
        public=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        signers.append((role,kid,private,base64.b64encode(public).decode()))
    registry={"schemaVersion":1,"issuer":"handraw-phase22-independent-audit",
              "keys":[{"keyId":kid,"role":role,"publicKeyBase64":pub}
                      for role,kid,_,pub in signers]}
    packet={"schemaVersion":1,"witnesses":[]}
    for n,kind in enumerate(sorted(source)):
        payload={"schemaVersion":1,"scope":kind,
             "webSha":WEB,"skillSha":SKILL,
             "sourceDigestSha256":source[kind],
             "recordedAtUtc":"2026-11-10T02:59:00Z",
             "witnessSessionId":"fixture-run-20261110",
             "nonce":f"nonce-fixture-{n:03d}",
             "result":"reviewed_source_claim_only"}
        packet["witnesses"].append({"payload":payload,
             "signatures":[{"role":role,"keyId":kid,
             "signatureBase64":base64.b64encode(priv.sign(canon(payload))).decode()}
             for role,kid,priv,_ in signers]})
    return official,records,packet,registry,master,critical,p,h


class Phase22FullChainTests(unittest.TestCase):
    def setUp(self):
        (self.official,self.records,self.packet,self.registry,
         self.master,self.critical,self.p,self.h)=bundle()

    def run_chain(self,**changes):
        args={"official_inputs":self.official,"field_records":self.records,
              "witnesses":self.packet,"witness_registry":self.registry,
              "master":self.master,"critical":self.critical,
              "provider":self.p,"handraw":self.h,
              "official_pin":sha(self.official["trust_registry"]),
              "field_pin":sha(self.registry),
              "web_sha":WEB,"skill_sha":SKILL,"now":NOW}
        args.update(changes)
        return evaluate_all(**args)

    def test_synthetic_green_structural_crosswalk_cannot_approve_real_d(self):
        result=self.run_chain()
        self.assertEqual(result["signedSourceClaimCount"],6)
        self.assertEqual(result["physicalProtocolDetailReceiptsLinked"],3)
        self.assertEqual(result["claimedDCaseCount"],17)
        self.assertTrue(result["redisDCaseHashBound"])
        self.assertTrue(result["realPaidProviderRawLedgerReconciledOffline"])
        for flag in ("actualWebsiteEditorialAuthorizationIndependentlyEstablished",
                     "realObjectStorageOrPostgresAccessPerformed",
                     "productionEnvironmentAccessPerformed",
                     "independentPhysicalDGradeAuditorApproved",
                     "autoReleaseOrIssueCloseAuthorized"):
            self.assertFalse(result[flag])
        self.assertEqual(result["decision"],"NO-GO")

    def test_missing_actual_official_bundle_and_forged_registry_refused(self):
        fake=deepcopy(self.official)
        fake["approvals"]=None
        with self.assertRaises(ValueError):self.run_chain(official_inputs=fake)
        with self.assertRaises(ValueError):self.run_chain(field_pin="f"*64)
        bogus=deepcopy(self.registry)
        bogus["keys"][0]["keyId"]="attacker"
        with self.assertRaises(ValueError):self.run_chain(witness_registry=bogus)
        altered=deepcopy(self.official)
        altered["source_receipt"]["sourceRowsSha256"]="f"*64
        with self.assertRaises(ValueError):self.run_chain(official_inputs=altered)

    def test_missing_field_and_replaced_provider_rows_or_signed_witness_refused(self):
        records=deepcopy(self.records)
        records["redis"]["measurements"]["noDuplicateWorkOrCharge"]=False
        with self.assertRaises(ValueError):self.run_chain(field_records=records)
        packet=deepcopy(self.packet)
        packet["witnesses"].pop()
        with self.assertRaises(ValueError):self.run_chain(witnesses=packet)
        h=deepcopy(self.h)
        h["attempts"][0]["status"]="refunded"
        with self.assertRaises(ValueError):self.run_chain(handraw=h)

    def test_d_grade_master_redis_hash_and_critical_summary_must_agree(self):
        master=deepcopy(self.master)
        next(x for x in master["cases"] if x["caseId"]=="redis_multi_instance_failover")[
            "evidenceDigestSha256"]="f"*64
        with self.assertRaises(ValueError):self.run_chain(master=master)
        critical=deepcopy(self.critical)
        next(x for x in critical["receipts"] if x["kind"]=="provider")[
            "details"]["refundCount"]=5
        with self.assertRaises(ValueError):self.run_chain(critical=critical)

    def test_public_cli_cannot_synthesize_field_signers(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=["--official-inputs",str(Path(tmp)/"no-official.json"),
                  "--field-records",str(Path(tmp)/"no-fields.json"),
                  "--witnesses",str(Path(tmp)/"no-sigs.json"),
                  "--witness-registry",str(Path(tmp)/"no-registry.json"),
                  "--master",str(Path(tmp)/"no-master.json"),
                  "--critical",str(Path(tmp)/"no-critical.json"),
                  "--provider",str(Path(tmp)/"no-provider.json"),
                  "--handraw",str(Path(tmp)/"no-wallet.json"),
                  "--web-sha",WEB,"--skill-sha",SKILL,
                  "--report",str(Path(tmp)/"no-go.json")]
            self.assertEqual(main(base),2)
            self.assertFalse((Path(tmp)/"no-go.json").exists())


if __name__=="__main__":
    unittest.main()
