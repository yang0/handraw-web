"""Phase22 reconciles provider paid ledger and independent free quota, never GO."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.reconcile_provider_statement_112 import BadEvidence
from ops.studio_phase22_provider_gate_132 import CASES,evaluate,main

SHA="a"*40
PERIOD=("2026-11-01T00:00:00Z","2026-11-02T00:00:00Z")


def fixture():
    p={"environment":"preproduction","window":{"start_utc":PERIOD[0],
       "end_utc":PERIOD[1]}}
    h={"environment":"preproduction"}
    q={"schemaVersion":1,"source":"handraw-independent-free-quota",
       "environment":"preproduction","releaseSha":SHA,
       "periodStartUtc":PERIOD[0],"periodEndUtc":PERIOD[1],
       "beforeQuota":10,"grantedQuota":5,"consumedQuota":7,
       "restoredQuota":1,"afterQuota":9,
       "freeTaskCount":7,"unmatchedFreeTaskCount":0,
       "independentExportSha256":"f"*64}
    s={"schemaVersion":1,"source":"independent-scenario-receipts",
       "environment":"preproduction","releaseSha":SHA,
       "periodStartUtc":PERIOD[0],"periodEndUtc":PERIOD[1],
       "providerStatementSha256":"b"*64,
       "handrawLedgerSha256":"c"*64,
       "freeQuotaSha256":"d"*64,
       "scenarios":[{"case":x,"observedCount":1,
          "evidenceSha256":format(i,"064x"),
          "operatorId":f"operator-{i}","reviewerId":f"reviewer-{i}"}
             for i,x in enumerate(CASES,start=1)]}
    return p,h,q,s


def paid_ok(*_):
    return {"releaseSha":SHA,"result":"NO_AUTOMATED_ANOMALIES",
            "anomalies":[],"currencyUnitsSeparated":True}


def run_case(p,h,q,s):
    return evaluate(p,h,q,s,web_sha=SHA,
        provider_bytes_sha="b"*64,
        handraw_bytes_sha="c"*64,
        free_bytes_sha="d"*64)


class Phase22ProviderTest(unittest.TestCase):
    @patch("ops.studio_phase22_provider_gate_132.reconcile",side_effect=paid_ok)
    def test_conservation_and_all_seven_independent_cases_remain_no_go(self,_):
        out=run_case(*fixture())
        self.assertTrue(out["allSevenScenarioReferencesPresent"])
        self.assertTrue(out["freeQuotaConservationMatched"])
        self.assertFalse(out["providerOriginalInvoiceAuthenticatedIndependently"])
        self.assertFalse(out["releaseAuthorized"])
        self.assertEqual(out["verifiedRealDPassCount"],0)
        self.assertEqual(out["decision"],"NO-GO")

    @patch("ops.studio_phase22_provider_gate_132.reconcile",side_effect=paid_ok)
    def test_tampered_quota_missing_scenario_duplicate_evidence_rejected(self,_):
        for key,bad in (("afterQuota",10),("unmatchedFreeTaskCount",1),
                        ("freeTaskCount",0),("releaseSha","b"*40)):
            p,h,q,s=fixture()
            q[key]=bad
            with self.subTest(field=key),self.assertRaises(BadEvidence):
                run_case(p,h,q,s)
        p,h,q,s=fixture()
        s["scenarios"].pop()
        with self.assertRaises(BadEvidence):run_case(p,h,q,s)
        p,h,q,s=fixture()
        s["scenarios"][1]["evidenceSha256"]=s["scenarios"][0]["evidenceSha256"]
        with self.assertRaises(BadEvidence):run_case(p,h,q,s)
        p,h,q,s=fixture()
        s["scenarios"][0]["reviewerId"]=s["scenarios"][0]["operatorId"]
        with self.assertRaises(BadEvidence):run_case(p,h,q,s)

    @patch("ops.studio_phase22_provider_gate_132.reconcile",side_effect=paid_ok)
    def test_manifest_artifact_drift_refused(self,_):
        p,h,q,s=fixture()
        s["providerStatementSha256"]="e"*64
        with self.assertRaises(BadEvidence):run_case(p,h,q,s)
        p,h,q,s=fixture()
        s["periodEndUtc"]="2026-11-03T00:00:00Z"
        with self.assertRaises(BadEvidence):run_case(p,h,q,s)
        p,h,q,s=fixture()
        s["scenarios"][0]["observedCount"]=0
        with self.assertRaises(BadEvidence):run_case(p,h,q,s)
        p,h,q,s=fixture()
        s["scenarios"][0]["case"]="fake-event"
        with self.assertRaises(BadEvidence):run_case(p,h,q,s)

    @patch("ops.studio_phase22_provider_gate_132.reconcile",
           return_value={"releaseSha":SHA,"result":"ANOMALIES",
                         "anomalies":[{"code":"double_bill"}]})
    def test_actual_paid_invoice_anomaly_cannot_be_suppressed(self,_):
        with self.assertRaises(BadEvidence):run_case(*fixture())

    def test_cli_cannot_accept_missing_private_actual_sources(self):
        with tempfile.TemporaryDirectory() as td:
            paths=[str(Path(td)/x) for x in ("provider.json","handraw.json",
                      "free.json","scenarios.json")]
            report=str(Path(td)/"report.json")
            self.assertEqual(main(["--provider",paths[0],"--handraw",paths[1],
                                  "--free",paths[2],"--scenarios",paths[3],
                                  "--web-sha",SHA,"--report",report]),2)
            self.assertFalse(Path(report).exists())


if __name__=="__main__":
    unittest.main()
