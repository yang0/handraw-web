"""#11/#84/#112 Phase 12 read-only release fixture inventory (NOT sign-off).

CI's PG17 is a disposable Postgres service; S3 is moto. Neither proves
production R2/S3, Redis multi-instance, billing, refund or real low-end GPU.
Never read credential values, upload backups or mutate a Skill catalog.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Invoked by CI as "python ops/phase12_release_preflight_112.py".
# Script execution puts /ops (not repo root) on sys.path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.check_official_catalog_parity import audit

EXPECTED_PENDING = {"FF-018": ("style", 11),
                    "FF-019": ("style", 132),
                    "FG-025": ("style", 11)}
PINNED_CLIENT_SHA = "dad8dad2d2af25bd9df45971a03a499461a723db"
SHA = re.compile(r"^[a-f0-9]{40}$")

MANUAL_GATES = (
    "Web editorial approval and published official DB export for #11",
    "Web + actual Skill main official catalog strict parity",
    "Real Web/Skill six-image task public Work and access isolation",
    "Actual R2/S3 signed uploads and multi-image retrieval",
    "Redis distributed locks, failover and multi-instance recovery",
    "Real vendor billing/debit/refund reconciliation",
    "PG17 staging backup/restore rollback from approved disposable source",
    "Physical low-end CPU/GPU/VRAM measurement",
    "Release-owner signoff and rollback rehearsal",
)


def _json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha(repo):
    if not (repo / ".git").exists():
        return None
    try:
        process = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        sha=process.stdout.strip()
        return sha if SHA.fullmatch(sha) else None
    except (OSError, subprocess.SubprocessError):
        return None


def pending_summary(manifest):
    if not isinstance(manifest, dict) or manifest.get("schemaVersion")!=1:
        raise ValueError("unknown pending resource manifest format")
    rows=manifest.get("pendingSkillOnly")
    if not isinstance(rows,list):
        raise ValueError("expected pending official resource array")
    pending={}
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("invalid pending proposal")
        code=row.get("code")
        if code in pending or code not in EXPECTED_PENDING:
            raise ValueError("unexpected or duplicate proposal")
        if (row.get("kind"), row.get("issue"))!=EXPECTED_PENDING[code]:
            raise ValueError("proposal kind/Issue does not match")
        if row.get("state")!="awaiting_website_editorial_review":
            raise ValueError("proposal review state changed; require review")
        if not isinstance(row.get("sha256"),str) or not re.fullmatch(
            r"[a-f0-9]{64}",row["sha256"]):
            raise ValueError("proposal source fingerprint missing")
        pending[code]={"issue":row["issue"],"kind":row["kind"],
                       "state":"awaiting_website_editorial_review",
                       "sourceFingerprintPresent":True}
    if set(pending)!=set(EXPECTED_PENDING):
        raise ValueError("expected all fingerprinted pending catalog IDs")
    return dict(sorted(pending.items()))


def prepare(repo_root, skill_root=None, skill_client=None,
            approved_export_dir=None):
    repo_root=Path(repo_root)
    manifest=pending_summary(_json(
        repo_root/"ops/official_catalog_pending_11.json"))
    skill_root=Path(skill_root) if skill_root else None
    skill_client=Path(skill_client) if skill_client else None
    export=Path(approved_export_dir) if approved_export_dir else None
    source_checked=bool(skill_root and
        (skill_root/"references/styles.json").is_file() and
        (skill_root/"references/layouts.json").is_file())
    client_checked=bool(skill_client and skill_client.is_file())
    checkout_sha=_sha(skill_client.parents[3]) if client_checked else None
    # The pinned executable must be this exact reviewed commit, not mutable
    # Skill main. Git reference catalogs can come from main, read-only.
    pinned_client_verified=client_checked and checkout_sha==PINNED_CLIENT_SHA
    approved_checked=bool(export and
        (export/"styles.json").is_file() and
        (export/"layouts.json").is_file())
    result={
        "phase":12,"relatedIssues":[11,84,112],
        "catalog":{"pending":manifest,
                   "skillMainReferenceDataAvailable":source_checked,
                   "actualWebApprovedExportAvailable":approved_checked,
                   "strictReleaseParityProven":False,
                   "publishingChangesMade":False},
        "skill":{"pinnedClientSourceAvailable":client_checked,
                 "pinnedClientShaMatches":bool(pinned_client_verified),
                 "expectedPinnedSha":PINNED_CLIENT_SHA,
                 "observedPinnedSha":checkout_sha,
                 "actualWebSkillLivePublishVerified":False},
        "existingCi":{"postgresql17DisposableTest":(
            repo_root/"tests/test_pg_backup_restore_112.py").is_file(),
            "motoS3EmulationTest":(
                repo_root/"tests/test_studio_skill_pg_s3_112.py").is_file(),
            "realStorageProviderProven":False,
            "realPaymentRefundProven":False,
            "redisMultiInstanceProven":False},
        "manualGates":[{"requirement":s,"verified":False}
                       for s in MANUAL_GATES],
        "readyForRelease":False,
        "productionNoGo":True,
        "containsSecretsOrCustomerData":False,
    }
    if source_checked:
        from ops.check_official_catalog_parity import _read
        approved_style=(_read(export/"styles.json") if approved_checked
                        else None)
        approved_layout=(_read(export/"layouts.json") if approved_checked
                         else None)
        report=audit(_json(repo_root/"plugin/content/catalog.json"),
                     _json(skill_root/"references/styles.json"),
                     _json(skill_root/"references/layouts.json"),
                     _json(repo_root/"ops/official_catalog_pending_11.json"),
                     strict=False,approved_styles=approved_style,
                     approved_layouts=approved_layout)
        result["catalog"]["observedParity"]={
            k:report[k] for k in ("status","webCount","skillCount",
                "knownPending","unexpectedSkillOnly","webOnly",
                "mismatchedKind","mismatchedName","alteredPending",
                "readyForRelease")}
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root",type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument("--skill-root",type=Path)
    p.add_argument("--skill-client",type=Path)
    p.add_argument("--approved-export-dir",type=Path)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    result=prepare(args.repo_root,args.skill_root,args.skill_client,
                   args.approved_export_dir)
    if args.skill_root and not result["catalog"]["skillMainReferenceDataAvailable"]:
        raise RuntimeError("Skill main reference catalog missing")
    if args.skill_client and not result["skill"]["pinnedClientShaMatches"]:
        raise RuntimeError("Skill client SHA did not match CI pinned version")
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    print("PHASE12 PREFLIGHT "+json.dumps({
        "pendingIds":list(result["catalog"]["pending"]),
        "observedParity":result["catalog"].get("observedParity"),
        "pinnedClient":result["skill"]["pinnedClientShaMatches"],
        "productionNoGo":True},ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
