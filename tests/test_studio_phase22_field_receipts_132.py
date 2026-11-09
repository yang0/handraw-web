"""Phase22 measured PG17 PITR/R2/CDN/Redis failover receipts fail closed."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ops.studio_phase22_field_receipts_132 import PG,ST,REDIS,evaluate,main

WEB="a"*40
SKILL="b"*40
H="c"*64


def good():
    pg={k:H for k in PG if k.endswith("Sha256")}
    pg.update({"sourcePhysicalHostSha256":"a"*64,
               "recoveryPhysicalHostSha256":"b"*64,
               "targetUtc":"2026-11-09T20:00:00Z",
               "recoveredReplayLsn":"0/1100ABCD",
               "pg17PhysicalBackupVerified":True,
               "pg17WalReplayAtTarget":True,
               "rollbackDrilled":True,
               "rpoBudgetSeconds":300,"rpoMeasuredSeconds":90,
               "rtoBudgetSeconds":1800,"rtoMeasuredSeconds":640})
    st={k:H for k in ST if k.endswith("Sha256")}
    st.update({k:True for k in ST if not k.endswith("Sha256")})
    st["tenantOneScopeSha256"]="a"*64
    st["tenantTwoScopeSha256"]="b"*64
    rd={k:H for k in REDIS if k.endswith("Sha256")}
    rd.update({k:True for k in REDIS
               if not k.endswith("Sha256") and not k.startswith("fencedLeaderEpoch")})
    rd["fencedLeaderEpochBefore"]=100
    rd["fencedLeaderEpochAfter"]=101
    return {"schemaVersion":1,"environment":"preproduction",
            "webSha":WEB,"skillSha":SKILL,
            "postgres":pg,"storage":st,"redis":rd}


class Phase22FieldReceiptsTests(unittest.TestCase):
    def test_complete_synthetic_receipt_never_grants_real_d_or_go(self):
        out=evaluate(good(),web_sha=WEB,skill_sha=SKILL)
        self.assertTrue(out["claimShapeAndCrossRecordInvariants"])
        self.assertEqual(out["realDCasePassGranted"],0)
        self.assertFalse(out["independentOriginalBytesVerifiedHere"])
        self.assertFalse(out["physicalHardwareOrProviderAuthenticatedHere"])
        self.assertFalse(out["productionReleaseAuthorized"])
        self.assertEqual(out["decision"],"NO-GO")

    def test_pg17_distinct_physical_host_wal_business_and_rpo_invariants(self):
        for field,bad in (("recoveryPhysicalHostSha256","a"*64),
                          ("walletLedgerAfterSha256","d"*64),
                          ("pg17WalReplayAtTarget",False),
                          ("rollbackDrilled",False),
                          ("rpoMeasuredSeconds",301),
                          ("rtoMeasuredSeconds",1801),
                          ("recoveredReplayLsn",""),
                          ("targetUtc","yesterday")):
            x=good()
            x["postgres"][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(x,web_sha=WEB,skill_sha=SKILL)

    def test_storage_anon_a_b_and_tombstone_not_shortcircuitable(self):
        for field,bad in (("anonymousDenied",False),
                          ("crossTenantReadDeniedBothDirections",False),
                          ("crossTenantWriteDeniedBothDirections",False),
                          ("cdnTombstoneDenied",False),
                          ("revokedUrlDenied",False),
                          ("expiredUrlDenied",False),
                          ("restoredObjectBytesSha256","d"*64),
                          ("tenantTwoScopeSha256","a"*64)):
            x=good()
            x["storage"][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(x,web_sha=WEB,skill_sha=SKILL)

    def test_redis_fencing_and_split_brain_fail_closed(self):
        for field,bad in (("fencedLeaderEpochAfter",100),
                          ("oldLeaderWritesRejected",False),
                          ("newLeaderResumed",False),
                          ("noDuplicateRunExecution",False),
                          ("crossTenantKeysDenied",False),
                          ("twoPhysicalInstanceWitnesses",False),
                          ("failoverPerformed",False)):
            x=good()
            x["redis"][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):
                evaluate(x,web_sha=WEB,skill_sha=SKILL)

    def test_stale_shas_and_unknown_receipt_fields_refused(self):
        x=good()
        x["webSha"]="d"*40
        with self.assertRaises(ValueError):
            evaluate(x,web_sha=WEB,skill_sha=SKILL)
        x=good()
        x["postgres"]["secret"]="not acceptable"
        with self.assertRaises(ValueError):
            evaluate(x,web_sha=WEB,skill_sha=SKILL)
        x=good()
        x["environment"]="production"
        with self.assertRaises(ValueError):
            evaluate(x,web_sha=WEB,skill_sha=SKILL)

    def test_private_cli_rejects_missing_input_and_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            args=["--dossier",str(d/"missing.json"),
                  "--web-sha",WEB,"--skill-sha",SKILL,
                  "--report",str(d/"report.json")]
            self.assertEqual(main(args),2)
            self.assertFalse((d/"report.json").exists())
            (d/"missing.json").write_text(json.dumps(good()))
            (d/"missing.json").chmod(0o600)
            self.assertEqual(main(args),0)
            self.assertEqual(json.loads((d/"report.json").read_text())["decision"],"NO-GO")
            self.assertEqual(main(args),2)


if __name__=="__main__":
    unittest.main()
