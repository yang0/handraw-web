"""#132 offline release audit workbench: human-readable review, NEVER GO.

Read-only evidence joins reuse Phase24; does not authenticate original sources.
No network, providers, Web DB, wallets or production services are accessed.
The private audit result contains only fixed gate names, states and public SHAs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.studio_d_environment_assertions_132 import (
    GATES, SHA, _private as read_claims, evaluate as evaluate_claims,
)
from ops.studio_d_receipt_contract_132 import GATES as DETAIL_GATES, _private as read_receipts
from ops.studio_phase22_field_receipts_132 import _private as read_field
from ops.studio_phase22_witness_chain_132 import SOURCES, _private as read_proof
from ops.studio_phase24_release_join_132 import evaluate as evaluate_bundle

INPUTS = ("claims", "receipts", "field-dossier", "registry", "proof-dir", "trust-sha")
CODES = ("FF-018", "FF-019", "FG-025")
HASH = re.compile(r"^[a-f0-9]{64}$")


def evaluate(claims=None, receipts=None, field_dossier=None, registry=None,
             proofs=None, *, trust_sha="", web_sha, skill_sha, now=None):
    """Only a structural assessment. CLAIMED_PASS is never a verified D PASS."""
    if (not isinstance(web_sha, str) or not SHA.fullmatch(web_sha)
            or not isinstance(skill_sha, str) or not SHA.fullmatch(skill_sha)):
        raise ValueError("full Web and Skill SHAs required")
    matrix = evaluate_claims(claims, web_sha=web_sha, skill_sha=skill_sha, now=now)
    available = {
        "claims": claims is not None,
        "receipts": receipts is not None,
        "field-dossier": field_dossier is not None,
        "registry": registry is not None,
        "proof-dir": isinstance(proofs, dict) and set(proofs) == set(SOURCES),
        "trust-sha": isinstance(trust_sha, str) and bool(HASH.fullmatch(trust_sha)),
    }
    missing = [name for name in INPUTS if not available[name]]
    states = {
        gate: ("CLAIMED_PASS_UNVERIFIED" if state == "PASS" else state)
        for gate, state in matrix["statusByCase"].items()
    }
    structure = "INCOMPLETE"
    if not missing:
        joined = evaluate_bundle(
            claims, receipts, field_dossier, registry, proofs,
            trust_sha=trust_sha, web_sha=web_sha, skill_sha=skill_sha, now=now,
        )
        if joined["decision"] != "NO-GO" or joined["verifiedRealDPassCount"] != 0:
            raise ValueError("unsafe upstream release result")
        structure = "STRUCTURALLY_CONSISTENT_UNVERIFIED"
    return {
        "schemaVersion": 1,
        "issue": 132,
        "releaseSha": web_sha,
        "skillSha": skill_sha,
        "decision": "NO-GO",
        "releaseAuthorized": False,
        "issueClosureAuthorized": False,
        "verifiedRealDPassCount": 0,
        "claimedPassCount": matrix["claimedPassCount"],
        "requiredDCaseCount": len(GATES),
        "evidenceStructure": structure,
        "missingInputs": missing,
        "dCaseStates": states,
        "detailedReceiptCoverage": {
            name: ("SUBMITTED_UNVERIFIED" if receipts is not None
                   and isinstance(receipts, dict)
                   and name in {row.get("kind") for row in receipts.get("receipts", [])
                                if isinstance(row, dict)} else "MISSING")
            for name in DETAIL_GATES
        },
        "independentWitnessCoverage": {
            name: ("SUBMITTED_UNVERIFIED" if proofs and name in proofs else "MISSING")
            for name in SOURCES
        },
        "officialCandidateApproval": {name: "NOT_INDEPENDENTLY_VERIFIED" for name in CODES},
        "sourceAuthenticityIndependentlyVerified": False,
        "productionInfrastructureContacted": False,
        "humanDualApprovalPerformed": False,
        "explanation": "Submitted evidence is a claim, not independent D-level verification.",
    }


def render_html(report):
    """Static HTML, no scripts, external resources or user-supplied evidence text."""
    def cell(value):
        return escape(str(value), quote=True)
    rows = "".join(
        "<tr><td>" + cell(case_id) + "</td><td>" + cell(state) + "</td></tr>"
        for case_id, state in report["dCaseStates"].items()
    )
    witness = "".join(
        "<tr><td>" + cell(name) + "</td><td>" + cell(state) + "</td></tr>"
        for name, state in report["independentWitnessCoverage"].items()
    )
    details = "".join(
        "<tr><td>" + cell(name) + "</td><td>" + cell(state) + "</td></tr>"
        for name, state in report["detailedReceiptCoverage"].items()
    )
    pending = "".join(
        "<tr><td>" + cell(name) + "</td><td>NOT INDEPENDENTLY VERIFIED</td></tr>"
        for name in CODES
    )
    gaps = ", ".join(cell(x) for x in report["missingInputs"]) or "All claim packet slots supplied"
    return (
        '<!doctype html><html lang="zh"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        'style-src &#39;unsafe-inline&#39;; img-src &#39;none&#39;; connect-src &#39;none&#39;; '
        'form-action &#39;none&#39;">'
        '<title>Studio 2.0 · Release Audit · NO-GO</title><style>'
        'body{font:15px system-ui,sans-serif;max-width:1140px;margin:auto;padding:36px;'
        'background:#fafbfc;color:#16202c}h1{font-size:26px}h2{margin-top:32px}'
        'table{width:100%;border-collapse:collapse;background:#fff}'
        'th,td{text-align:left;padding:10px;border-bottom:1px solid #e2e7ee}'
        'th{background:#edf1f5}.blocked{font-weight:700;color:#9c2634}'
        'code{overflow-wrap:anywhere}p{line-height:1.6}</style></head><body>'
        '<h1>Studio 2.0 · 发布审核工作台</h1>'
        '<p class="blocked">NO-GO · 真实 D 级独立通过 0 / ' + cell(report["requiredDCaseCount"]) + '</p>'
        '<p>Web SHA：<code>' + cell(report["releaseSha"]) + '</code><br>'
        'Skill SHA：<code>' + cell(report["skillSha"]) + '</code><br>'
        '证据结构：' + cell(report["evidenceStructure"]) + '<br>'
        '待补证据入口：' + gaps + '</p>'
        '<p>本页只能核查提交材料的结构一致性；不能证明原始来源、授权、'
        '真实硬件、供应商账单或正式签核。即使所有 CLAIMED_PASS 也绝不允许发布。</p>'
        '<h2>17 项 D 级门禁</h2><table><thead><tr><th>检查项</th><th>状态</th></tr></thead>'
        '<tbody>' + rows + '</tbody></table>'
        '<h2>五类独立来源见证</h2><table><thead><tr><th>来源</th><th>状态</th></tr></thead>'
        '<tbody>' + witness + '</tbody></table>'
        '<h2>三项详细收据</h2><table><thead><tr><th>对象</th><th>状态</th></tr></thead>'
        '<tbody>' + details + '</tbody></table>'
        '<h2>网站官方资源候选</h2><table><thead><tr><th>编号</th><th>状态</th></tr></thead>'
        '<tbody>' + pending + '</tbody></table>'
        '<p class="blocked">PR #131 保持 Draft；Issue #132 保持 Open；生产发布 NO-GO。</p>'
        '</body></html>'
    )


def _safe_output_dir(path):
    folder = Path(path)
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError("existing absolute private output directory required")
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise ValueError("output directory symlink or symlink ancestor")
    if os.name == "posix" and stat.S_IMODE(folder.stat().st_mode) & 0o077:
        raise ValueError("output directory must be private 0700")
    for name in ("release-audit.json", "review.html"):
        out = folder / name
        if out.exists() or out.is_symlink():
            raise ValueError("will not overwrite audit report")
    return folder


def _new_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--web-sha", required=True)
    ap.add_argument("--skill-sha", required=True)
    ap.add_argument("--claims", type=Path)
    ap.add_argument("--receipts", type=Path)
    ap.add_argument("--field-dossier", type=Path)
    ap.add_argument("--registry", type=Path)
    ap.add_argument("--proof-dir", type=Path)
    ap.add_argument("--trust-sha", default="")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--mode", choices=("gate", "audit"), default="gate",
                    help="gate always exits blocked; audit writes a NO-GO review and exits 0")
    args = ap.parse_args(argv)
    try:
        folder = _safe_output_dir(args.out_dir)
        if args.proof_dir and (not args.proof_dir.is_dir()
                or any(p.is_symlink() for p in (args.proof_dir, *args.proof_dir.parents))):
            raise ValueError("unsafe private witness directory")
        proofs = None
        if args.proof_dir:
            proofs = {}
            for kind in SOURCES:
                path = args.proof_dir / (kind + ".json")
                if path.is_file():
                    proofs[kind] = read_proof(path)
        inputs = (args.claims, args.receipts, args.field_dossier, args.registry)
        present = [p for p in inputs if p is not None]
        if len({p.resolve(strict=True) for p in present}) != len(present):
            raise ValueError("duplicate evidence inputs")
        result = evaluate(
            read_claims(args.claims) if args.claims else None,
            read_receipts(args.receipts) if args.receipts else None,
            read_field(args.field_dossier) if args.field_dossier else None,
            read_proof(args.registry)[0] if args.registry else None,
            proofs, trust_sha=args.trust_sha,
            web_sha=args.web_sha, skill_sha=args.skill_sha,
        )
        _new_private(folder / "release-audit.json",
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        _new_private(folder / "review.html", render_html(result))
        print("STUDIO RELEASE WORKBENCH " + json.dumps({
            "decision":"NO-GO", "verifiedRealDPassCount":0,
            "claimedPassCount":result["claimedPassCount"],
            "missingInputCount":len(result["missingInputs"]),
            "evidenceStructure":result["evidenceStructure"],
            "releaseAuthorized":False,
        }, ensure_ascii=False))
        return 2 if args.mode == "gate" else 0
    except Exception:
        print("Studio release audit BLOCKED: private input or structure invalid",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
