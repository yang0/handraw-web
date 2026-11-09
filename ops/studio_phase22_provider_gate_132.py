"""Phase22 #132: full vendor billing + free quota + failure scenario ledger audit.

Reuses issue #112's independently normalized, *final and mature* vendor
invoice vs HandRaw run/item/attempt/wallet/callback reconciliation. Free quota
must be independently exported and tied to the same exact SHA/UTC period.
Never accesses provider, customer, website DB or authorizes production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from ops.reconcile_provider_statement_112 import (
    BadEvidence,reconcile,_private_read,_write_report,
)

HASH=re.compile(r"^[a-f0-9]{64}$")
SHA=re.compile(r"^[a-f0-9]{40}$")
CASES=("duplicate_callback","throttled_429","upstream_502",
       "unknown_recovery","late_success","refund","free_quota")
FIELDS={"schemaVersion","source","environment","releaseSha","periodStartUtc",
        "periodEndUtc","providerStatementSha256","handrawLedgerSha256",
        "freeQuotaSha256","scenarios"}
SCENARIO_FIELDS={"case","observedCount","evidenceSha256","operatorId","reviewerId"}
FREE_FIELDS={"schemaVersion","source","environment","releaseSha",
             "periodStartUtc","periodEndUtc","beforeQuota","grantedQuota",
             "consumedQuota","restoredQuota","afterQuota","freeTaskCount",
             "unmatchedFreeTaskCount","independentExportSha256"}


def _hash(value):
    if not isinstance(value,str) or not HASH.fullmatch(value):
        raise BadEvidence("invalid independently tracked original evidence hash")


def _counter(value):
    if type(value) is not int or not 0<=value<=10**12:
        raise BadEvidence("invalid non-negative count")


def evaluate(provider,handraw,free,scenario,*,web_sha,provider_bytes_sha,handraw_bytes_sha,free_bytes_sha):
    if not isinstance(web_sha,str) or not SHA.fullmatch(web_sha):
        raise BadEvidence("full release SHA required")
    for item in (provider_bytes_sha,handraw_bytes_sha,free_bytes_sha):
        _hash(item)
    # These are actual ledger invariants, not blindly accepted PASS flags.
    paid=reconcile(provider,handraw)
    if paid["releaseSha"]!=web_sha or paid["result"]!="NO_AUTOMATED_ANOMALIES" or paid["anomalies"]:
        raise BadEvidence("paid provider invoice vs wallet/callback anomalies")
    if not isinstance(free,dict) or set(free)!=FREE_FIELDS or free["schemaVersion"]!=1 or free["source"]!="handraw-independent-free-quota":
        raise BadEvidence("missing independent free quota export")
    if (free["environment"]!=provider["environment"] or free["releaseSha"]!=web_sha
        or free["periodStartUtc"]!=provider["window"]["start_utc"]
        or free["periodEndUtc"]!=provider["window"]["end_utc"]):
        raise BadEvidence("free and paid billing period/SHA drift")
    _hash(free["independentExportSha256"])
    for f in ("beforeQuota","grantedQuota","consumedQuota","restoredQuota",
              "afterQuota","freeTaskCount","unmatchedFreeTaskCount"):
        _counter(free[f])
    if (free["beforeQuota"]+free["grantedQuota"]-free["consumedQuota"]
        +free["restoredQuota"]!=free["afterQuota"] or free["unmatchedFreeTaskCount"]!=0
        or free["freeTaskCount"]<1):
        raise BadEvidence("free quota ledger conservation or coverage failed")
    if not isinstance(scenario,dict) or set(scenario)!=FIELDS or scenario["schemaVersion"]!=1 or scenario["source"]!="independent-scenario-receipts":
        raise BadEvidence("wrong scenario witness schema")
    if (scenario["environment"]!=provider["environment"] or scenario["releaseSha"]!=web_sha
        or scenario["periodStartUtc"]!=free["periodStartUtc"]
        or scenario["periodEndUtc"]!=free["periodEndUtc"]
        or scenario["providerStatementSha256"]!=provider_bytes_sha
        or scenario["handrawLedgerSha256"]!=handraw_bytes_sha
        or scenario["freeQuotaSha256"]!=free_bytes_sha
        or not isinstance(scenario["scenarios"],list) or len(scenario["scenarios"])!=len(CASES)):
        raise BadEvidence("scenario registry does not bind three original exports")
    seen=set();proofs=set()
    for row in scenario["scenarios"]:
        if not isinstance(row,dict) or set(row)!=SCENARIO_FIELDS:
            raise BadEvidence("unsafe scenario evidence fields")
        kind=row["case"]
        if kind not in CASES or kind in seen:
            raise BadEvidence("duplicate/missing scenario")
        seen.add(kind)
        _counter(row["observedCount"])
        if row["observedCount"]<1:
            raise BadEvidence("scenario not actually observed")
        _hash(row["evidenceSha256"])
        if row["evidenceSha256"] in proofs:
            raise BadEvidence("scenario evidence reused across independent conditions")
        proofs.add(row["evidenceSha256"])
        for f in ("operatorId","reviewerId"):
            if not isinstance(row[f],str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}",row[f]):
                raise BadEvidence("invalid auditor identity")
        if row["operatorId"]==row["reviewerId"]:
            raise BadEvidence("self-reviewed billing scenario")
    if set(seen)!=set(CASES):
        raise BadEvidence("missing required billing scenario")
    return {"phase":22,"issue":132,"scope":"vendor-wallet-free-quota",
            "paidReconciliation":"NO_AUTOMATED_ANOMALIES",
            "allSevenScenarioReferencesPresent":True,
            "freeQuotaConservationMatched":True,
            "providerOriginalInvoiceAuthenticatedIndependently":False,
            "scenarioOriginalsAuthenticatedIndependently":False,
            "sourceCurrencyAndFreeUnitsNotMixed":True,
            "verifiedRealDPassCount":0,"releaseAuthorized":False,
            "decision":"NO-GO"}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider",type=Path,required=True)
    ap.add_argument("--handraw",type=Path,required=True)
    ap.add_argument("--free",type=Path,required=True)
    ap.add_argument("--scenarios",type=Path,required=True)
    ap.add_argument("--web-sha",required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        paths=(args.provider,args.handraw,args.free,args.scenarios)
        if len({p.resolve() for p in paths})!=4:
            raise BadEvidence("four independent private artifacts required")
        docs=[_private_read(p) for p in paths]
        sha_bytes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths[:3]]
        result=evaluate(*docs,web_sha=args.web_sha,
            provider_bytes_sha=sha_bytes[0],
            handraw_bytes_sha=sha_bytes[1],
            free_bytes_sha=sha_bytes[2])
        _write_report(args.report,result)
        print("PHASE22 PROVIDER "+json.dumps({
            "billingClaimsConsistent":True,"decision":"NO-GO","realDPass":0}))
        return 0
    except Exception:
        print("Phase22 provider billing gate BLOCKED",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
