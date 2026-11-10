# Studio 2.0 · Issue #132 · Unified Release Audit Workbench

2026-11-10 · Engineering-level offline audit capability. This is **not D-level proof or GO authorization**. Production remains NO-GO; PR #131 remains Draft; main cannot change.

## A real PG17 evidence-contract defect is fixed

The old detailed Postgres receipt contract required sourceClusterIdSha256 and restoreClusterIdSha256 to differ. That was incorrect for a PostgreSQL **physical** basebackup: the recovered database cluster must preserve the **same system_identifier**. Phase28 independently added a read-only recovery-system-identifier check against source-side witness. This slice updates the earlier detailed receipt contract to **require matching source/restore system identifiers**, with synthetic regression fixtures now exercising the same condition. A truly independent physical host is demonstrated separately by sourcePhysicalHostSha256 != recoveryPhysicalHostSha256 in the Phase22 field dossier. Matching cluster identities never proves the machines are independent, nor that the witness is authentic; those require an external human audit.

## Unified operator command

Run on a dedicated isolated reviewer machine. Output directory must already exist as an absolute, owner-only 0700 directory. The tool writes two new non-overwriting 0600 files: release-audit.json and review.html.

To list outstanding D-level evidence with no secret inputs, run:

    mkdir -m 700 /secure/studio-release-audit-132
    python ops/studio_release_audit_workbench_132.py \
      --web-sha <40-character-deployed-web-sha> \
      --skill-sha <40-character-reviewed-skill-sha> \
      --out-dir /secure/studio-release-audit-132 --mode audit

This produces the complete 17-case, 3-detailed-receipt, 5-independent-witness and 3-official-candidate dashboard showing MISSING, BLOCKED, or CLAIMED_PASS_UNVERIFIED. It never contacts production, suppliers, PostgreSQL, Redis, R2, S3 or the website. --mode audit means only that the report was written successfully; the report decision is always NO-GO.

For an externally collected source packet, use a NEW output directory and provide all original Phase24 inputs:

    mkdir -m 700 /secure/studio-release-audit-132-new
    python ops/studio_release_audit_workbench_132.py \
      --web-sha <deployed-web-sha> --skill-sha <reviewed-skill-sha> \
      --claims /secure/studio-evidence/claims.json \
      --receipts /secure/studio-evidence/receipts.json \
      --field-dossier /secure/studio-evidence/field.json \
      --registry /secure/studio-evidence/registry.json \
      --proof-dir /secure/studio-evidence/proofs \
      --trust-sha <independent-registry-sha256> \
      --out-dir /secure/studio-release-audit-132-new --mode audit

The five proof files are official.json, postgres.json, storage.json, redis.json and provider.json. All artifacts must be pre-collected in the protected evidence vault with independently pinned SHA-256 and restrictive file permissions. The original bytes, signatures and human proof of source authenticity are NEVER produced by this script. Even if all claim packets are self-consistent, the only possible output state is STRUCTURALLY_CONSISTENT_UNVERIFIED with verifiedRealDPassCount=0, releaseAuthorized=false, humanDualApprovalPerformed=false and decision=NO-GO.

## Existing evidence validators are reused, not reinvented

The CLI imports the established 17-gate claim matrix from studio_d_environment_assertions_132.py, 3-detail receipt validator from studio_d_receipt_contract_132.py, PG17/R2-S3-CDN/Redis field dossier from studio_phase22_field_receipts_132.py, five independent witness SHA-pinned source reports from studio_phase22_witness_chain_132.py, and the full cross-source join from studio_phase24_release_join_132.py. The HTML is a static, escaped, no-script reviewer dashboard, protected by a strict content-security policy. Reports include only fixed case identifiers, enumeration states and publicly known Web/Skill SHAs; they never include private raw evidence, operator IDs, report paths, credentials, wallet rows, invoice amounts or images.

By default the CLI uses --mode gate: it writes the same useful NO-GO summary and returns exit code 2 to block any deployment pipeline. Never use the exit code 0 of --mode audit as an authorization signal. Incorrect or non-private evidence is rejected with exit code 2 and without a successful audit report.

The official FF-018, FF-019, FG-025 candidates continue to show NOT_INDEPENDENTLY_VERIFIED. Actual website editorial approval and published official-DB export with Web/Skill strict parity are separate necessary gates and cannot be inferred from a synthetic or self-signed claim. A low-level HTML review artifact is not a replacement for the authorized website's editorial approval workflow.

## Release discipline

The new slice stays on independent branch studio2-issue132-release-workbench-pg17-identity-20261110. Phase28 formal studio2 Push and Draft PR must first each reach 14/14, and this independent branch must also reach 14/14 with compare ahead>0/behind=0, main unchanged and PR #131 still Open Draft. Then and only then use update_ref with expected_sha and force=false, followed by the formal studio2 Push and PR 14/14 checks.

No real vendor bill, provider credentials, physical PG17 PITR, R2/S3/CDN, Redis failover, physical low-end device or actual official editorial signatures were provided. All 17 genuine D-level pass counts remain 0/17; Issue #132 remains Open/NO-GO.
