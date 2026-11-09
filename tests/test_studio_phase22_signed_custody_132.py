"""Phase22 Ed25519 custody: independent trust pin, source hash, nonce, strict website chain."""
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
from ops.studio_official_approval_132 import sha,canon
from ops.studio_phase22_signed_custody_132 import (
    SCOPES, evaluate, evaluate_linked, main,
)
from test_studio_phase21_official_gate_132 import fixture as official_fixture
from test_studio_phase22_field_matrix_132 import (
    event_packet,provider_sample,WEB,SKILL,NOW,
)


def signed_fixture():
    official=official_fixture()
    records={kind:event_packet(kind) for kind in ("postgres","storage","redis","provider")}
    expected={
        "official_web_export":sha(official["source_receipt"]),
        "skill_checkout":sha({"styles":official["skill_styles"],
             "layouts":official["skill_layouts"],"expectedGitSha":SKILL}),
        **{kind:sha(records[kind]) for kind in records},
    }
    keys=[]
    for role,kid in (("field_operator","separately-controlled-operator"),
                     ("independent_reviewer","separate-auditor")):
        key=Ed25519PrivateKey.generate()
        pub=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        keys.append((role,kid,key,base64.b64encode(pub).decode("ascii")))
    registry={"schemaVersion":1,"issuer":"handraw-phase22-independent-audit",
        "keys":[{"role":role,"keyId":kid,"publicKeyBase64":pub}
                for role,kid,_,pub in keys]}
    witnesses=[]
    for i,scope in enumerate(sorted(SCOPES)):
        payload={"schemaVersion":1,"scope":scope,"webSha":WEB,"skillSha":SKILL,
                 "sourceDigestSha256":expected[scope],
                 "recordedAtUtc":"2026-11-10T02:59:00Z",
                 "witnessSessionId":"phase22-offline-only","nonce":f"unique-nonce-{i:03d}",
                 "result":"reviewed_source_claim_only"}
        signs=[{"role":role,"keyId":kid,
           "signatureBase64":base64.b64encode(key.sign(canon(payload))).decode("ascii")}
           for role,kid,key,_ in keys]
        witnesses.append({"payload":payload,"signatures":signs})
    return official,records,expected,registry,{"schemaVersion":1,"witnesses":witnesses}


class Phase22SignedCustodyTests(unittest.TestCase):
    def setUp(self):
        self.official,self.records,self.expected,self.registry,self.packet=signed_fixture()
        self.pin=sha(self.registry)

    def verify(self,packet=None,registry=None,expected=None,pin=None):
        return evaluate(packet if packet is not None else self.packet,
            registry if registry is not None else self.registry,
            trusted_registry_sha=self.pin if pin is None else pin,
            expected_source_digests=self.expected if expected is None else expected,
            web_sha=WEB,skill_sha=SKILL,now=NOW)

    def test_six_independent_sources_have_valid_signatures_but_never_d_pass(self):
        out=self.verify()
        self.assertTrue(out["signedClaimPacketComplete"])
        self.assertEqual(out["signedSourceClaimsValidated"],6)
        self.assertEqual(out["missingScopes"],[])
        self.assertFalse(out["sourceAuthenticityIndependentlyProvenByThisTool"])
        self.assertFalse(out["physicalDGradeCertification"])
        self.assertFalse(out["automaticReleaseAuthorized"])
        self.assertEqual(out["decision"],"NO-GO")
        self.assertNotIn("unique-nonce",json.dumps(out))

    def test_missing_witnesses_never_implicitly_pass(self):
        packet=deepcopy(self.packet)
        packet["witnesses"]=packet["witnesses"][:1]
        out=self.verify(packet=packet)
        self.assertEqual(out["signedSourceClaimsValidated"],1)
        self.assertEqual(len(out["missingScopes"]),5)
        self.assertFalse(out["signedClaimPacketComplete"])

    def test_unsigned_payload_mutation_and_source_hash_mismatch_rejected(self):
        for field,new in (("sourceDigestSha256","f"*64),
                          ("webSha","c"*40),
                          ("skillSha","d"*40),
                          ("result","officially_approved"),
                          ("recordedAtUtc","2025-01-01T00:00:00Z"),
                          ("nonce","bad!")):
            packet=deepcopy(self.packet)
            packet["witnesses"][0]["payload"][field]=new
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.verify(packet=packet)
        expected=dict(self.expected)
        expected["provider"]="e"*64
        with self.assertRaises(ValueError):
            self.verify(expected=expected)

    def test_self_signed_roots_same_public_key_and_replayed_nonces_fail(self):
        bad=deepcopy(self.registry)
        bad["keys"][0]["keyId"]="attacker-own-key"
        with self.assertRaises(ValueError):
            self.verify(registry=bad)
        with self.assertRaises(ValueError):
            self.verify(pin="f"*64)
        bad=deepcopy(self.registry)
        bad["keys"][1]["publicKeyBase64"]=bad["keys"][0]["publicKeyBase64"]
        with self.assertRaises(ValueError):
            self.verify(registry=bad,pin=sha(bad))
        packet=deepcopy(self.packet)
        packet["witnesses"][1]["payload"]["nonce"]=packet["witnesses"][0]["payload"]["nonce"]
        with self.assertRaises(ValueError):
            self.verify(packet=packet)
        packet=deepcopy(self.packet)
        packet["witnesses"][1]["signatures"][1]["keyId"]=packet["witnesses"][1]["signatures"][0]["keyId"]
        with self.assertRaises(ValueError):
            self.verify(packet=packet)

    def test_full_phase21_signature_first_then_field_and_provider_chain(self):
        p,h=provider_sample()
        out=evaluate_linked(official_inputs=self.official,
            field_records=self.records,packet=self.packet,registry=self.registry,
            trusted_registry_sha=self.pin,web_sha=WEB,skill_sha=SKILL,
            provider=p,handraw=h,now=NOW)
        self.assertEqual(out["signedSourceClaimsValidated"],6)
        self.assertTrue(out["websiteEditorialSignatureClaimsValidated"])
        self.assertTrue(out["strictWebSkillParityDryRunPassed"])
        self.assertTrue(out["providerToWalletSourceReconciliationChecked"])
        self.assertFalse(out["independentRealWorldSiteAuditVerified"])
        self.assertEqual(out["decision"],"NO-GO")
        bad=deepcopy(self.official)
        bad["approvals"]=None
        with self.assertRaises(ValueError):
            evaluate_linked(official_inputs=bad,field_records=self.records,
                packet=self.packet,registry=self.registry,
                trusted_registry_sha=self.pin,web_sha=WEB,skill_sha=SKILL,
                provider=p,handraw=h,now=NOW)
        mutated=deepcopy(self.records)
        mutated["redis"]["measurements"]["noDuplicateWorkOrCharge"]=False
        with self.assertRaises(ValueError):
            evaluate_linked(official_inputs=self.official,field_records=mutated,
                packet=self.packet,registry=self.registry,
                trusted_registry_sha=self.pin,web_sha=WEB,skill_sha=SKILL,
                provider=p,handraw=h,now=NOW)

    def test_missing_external_registry_always_blocked_and_no_go_cli_is_safe(self):
        with tempfile.TemporaryDirectory() as root:
            report=Path(root)/"no-go.json"
            args=["--web-sha",WEB,"--skill-sha",SKILL,"--report",str(report)]
            self.assertEqual(main(args),0)
            self.assertEqual(json.loads(report.read_text())["decision"],"NO-GO")
            self.assertEqual(main(args),2)
            self.assertNotIn("signatureBase64",report.read_text())


if __name__=="__main__":
    unittest.main()
