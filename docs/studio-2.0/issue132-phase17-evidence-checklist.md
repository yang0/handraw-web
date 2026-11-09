# #132 · Phase 17 | DOM mutation ancestry + release D gate on-site checklist

**Status: C-level diagnostic only. Production release: NO-GO.** Applies to `studio2`, Draft PR #131 (do not merge into main), and open Issue #132. Evidence collected for this document is **not** proof that production prerequisites are satisfied. No production CSS/JS is changed.

## 1. Exact scope of initial-drag DOM changes

Phase 16 observed two added and two removed child nodes classified as `other` during the first synthetic pointermove on both 1× and simulated 4× CPUs. The role classifier previously inspected removed elements **after** DOM detachment; its `closest()` and layer membership results therefore could lose the parent ancestry.

The Phase 17 **test-page-only** MutationObserver now captures, at each `childList` record:
- `ancestorTags`: ordered parent lineage from the topmost still-attached ancestor toward the mutation parent (maximum 24 tags; only a finite HTML/SVG whitelist and `other-tag`).
- `nodeTag`: sanitized tag for the changed child (`#text` and `#comment` are explicit), `parentRole`: the **mutation parent** role at observation, `parentConnected`: whether the parent remains attached, and bounded `count`.
- Separate `added` / `removed` groups, with cardinality caps and validation that their totals equal the existing `mountCounts` totals. A detached child being `other` **does not** itself mean the parent was outside the canvas.
- No element IDs, attribute values, classes, selectors, user text, pointer coordinates, asset URLs, original Chrome Trace, or user media are persisted.

**Precise means tag-level ancestry in the observed DOM mutation record**, not an identifying CSS selector. If `parentConnected=false`, or the chain does not reach `html` (for example, in a detached subtree), the result **does not establish full document ancestry**. Repeated same-tag siblings remain indistinguishable. Observe and report these limitations rather than inventing IDs.

### Required experiment / causality bar

1. Use the same real test HTTP/SQLite Studio page: 300 node cards, 150 SVG edges, 120 independently decoded WebPs; Graph/Undo integrity, three explicitly untrusted synthetic moves, one real pointerdown, no vendor calls.
2. Capture `pre-input-idle`, `synthetic-move-1/2/3` individually for both 1× and simulated 4× CPU, with bounded native Chrome `UpdateLayoutTree` counts and invalidation reasons. Validate every lineage record and ensure observer restoration.
3. Compare whether new paths are under the graph/nodes layer, floating overlay, a sibling of the viewport, or outside the canvas. Note whether changes are text nodes, SVG elements, or HTML elements. Do not call the `other` result a floating layer without evidence.
4. To prove *causality* (rather than timing), independently suppress or reproduce only the identified test-only mutation source; run repeated A-B-A-B-A traces at both CPU factors and ensure unchanged visual/Graph/Undo behavior. **Do not modify shipped CSS/JS** unless a stable benefit is proven on both CPU modes and an independent production review authorizes it.
5. Browser synthetic CPU throttle is **not** a physical low-end hardware test. No Phase 17 result can satisfy the corresponding D gate by itself.

## 2. Website editorial release: FF-018 / FF-019 / FG-025

All three resources remain `awaiting_website_editorial_review`. The Skill `main` reference used for the baseline was `9248843ba4659a1d9afbc177ae73b91bb1af68a9`; Web static catalog: 537, Skill: 540. Candidate metadata SHA256 values are pinned in `ops/official_catalog_pending_11.json` only for drift detection, **not publication**.

For **each code independently** an authorized website operator must:
- Verify full candidate JSON/Skill commit, source image authorship, license/permissions, provenance of prompt and description, generic style suitability, and any attribution constraints. Record an access-controlled rights-review evidence ID.
- Approve in the official website management flow and publish in the authoritative Web official DB. Export the actual deployed `number`, `generation_name`, and full approved DB row from a verified read-only connection, alongside deployed Web SHA.
- Obtain **two separate organizational identities** and **different Ed25519 raw public key bytes**, roles `website_editor` and `independent_reviewer`. Security administrators pin the trust-registry SHA256 through independently controlled Vault/configuration. Sign the exact canonical payload, including full candidate fingerprint, published DB-row fingerprint, deployment SHA, action ID, rights evidence ID, UTC timestamp.
- Run the offline `ops/studio_official_approval_132.py` intake against private `0600` files. Verify the real DB export origin by a second authorized operator. The verifier cannot infer authority from a claimed exported file or an operator-supplied trust checksum.
- Reconcile actual Web-approved DB, static official catalog, and Skill index under `ops/check_official_catalog_parity.py --strict`; perform an independent Skill-side review/merge. If rights or approval fail, preserve draft/source and **do not** silently reverse-publish to Web or delete it from the Skill draft trail.

The code rejects two key IDs that reuse the same Ed25519 public bytes. Approval claims, including correctly signed test-only claims, **always** leave `automaticWebsiteApprovalGranted=false`, `decision=NO-GO`.

## 3. D-level private evidence bundle: 17 required cases

Use **one private record per case**. All values below are intentionally placeholders and are **not** production attestations. Prepare `0600` private JSON and do not commit it, raw logs, credentials, bills, real media or staff identities into GitHub. `ops/studio_d_environment_assertions_132.py` verifies declaration structure only.

Common required fields, exactly:

```json
{
  "schemaVersion": 1,
  "environment": "preproduction",
  "deployedSha": "FULL_40_HEX_DEPLOYED_WEB_SHA",
  "skillSha": "FULL_40_HEX_DEPLOYED_SKILL_SHA",
  "cases": [
    {
      "caseId": "editorial_ff018",
      "status": "PENDING",
      "origin": "website-published-db-and-editorial",
      "evidenceDigestSha256": "FULL_64_HEX_DIGEST_OF_PRIVATE_EVIDENCE",
      "evidenceId": "PRIVATE_UNIQUE_TOKEN",
      "environmentId": "PRIVATE_REAL_ENVIRONMENT_TOKEN",
      "deployedSha": "FULL_40_HEX_DEPLOYED_WEB_SHA",
      "skillSha": "FULL_40_HEX_DEPLOYED_SKILL_SHA",
      "observedAtUtc": "UTC_TIMESTAMP",
      "operator": "PRIVATE_OPERATOR_ID",
      "reviewer": "PRIVATE_DISTINCT_REVIEWER_ID",
      "isSimulation": false,
      "physicalOrRealProviderClaim": true
    }
  ]
}
```

Replace **every** placeholder with independently verifiable real facts. The example is intentionally invalid until completed; never set `isSimulation=false` for a synthetic test. `PASS` must refer to a reviewer-verified primary artifact (not merely a green CI job). A private source bundle should bind evidence digest, deployed SHA, environment ID, time, operator and independent reviewer and preserve full logs/objects under restricted access.

| Case ID | Required independent D-level verification / evidence |
| --- | --- |
| `editorial_ff018` | FF-018 rights, official Web approved DB row, dual-role editorial approval, published SHA |
| `editorial_ff019` | FF-019 same separate official provenance, source fingerprint, both signatures |
| `editorial_fg025` | FG-025 same separate website rights and approval |
| `web_db_and_skill_main_strict_parity` | Real approved Web DB export, Skill independently reviewed index, `--strict` parity with no pending exceptions |
| `one_run_one_public_work` | Actual Skill/Web run/item/attempt → one public work, stable IDs and billing projection |
| `five_images_out_of_order` | Five actual media objects with out-of-order callbacks, cover/ordering and per-item provenance |
| `three_success_two_failed` | Three success + two failures, proper billing/free quota, refunds and retry handling |
| `all_failed_zero_work` | All-failed run produces zero successful public work and fully reconciled costs |
| `skill_explicit_upload_resume_and_gif` | Independent device/real network upload resume, GIF bytes, retry and idempotency |
| `cover_moderation_tombstone` | Real CDN/objects confirm moderation tombstone, old URL invalidation and cache purge |
| `cross_user_private_media` | Two real test accounts confirm object/media isolation, signatures and ownership ACLs |
| `real_object_bucket_and_expired_url` | Real private R2/S3/MinIO gateway and CDN policy, expired signed links and restore |
| `redis_multi_instance_failover` | Actual multi-instance Redis lock contention, recovery and duplicate-work prevention |
| `real_provider_charge_refund_ledger` | Real vendor invoice/usage/charge/refund reconciliation to wallet, free quota, run/item/attempt |
| `pg17_offline_backup_restore_rollback` | Production-equivalent physical cold backup on separate host, WAL/PITR, migration rollback and data invariants |
| `low_end_physical_browser` | Actual low-end CPU/GPU/VRAM, physical touch and weak network; full Canvas performance, not CDP throttle |
| `release_owner_rollback_signoff` | Deployed Web/Skill SHA, UTC, evidence IDs, environment/version, independent dual signoff, measured RPO/RTO and tested rollback |

### Independent reviewer signoff

For each row: compare raw evidence digest (do not copy sensitive bytes), source system and immutable activity time; verify the real environment, configured deployment SHA, operational ownership, independent witness, error/retry cases, cleanup and legal provenance. Document reasoned FAIL/BLOCKED/PENDING states rather than filling PASS speculatively.

Final hard stop: **no automatic GO mechanism**. Even 17/17 structurally valid `PASS` claims must return `decision=NO-GO` / `issueClosureAuthorized=false` until independent real-world verification, official Web/Skill dual approvals, and explicit human release authorization are performed. Issue #132 remains open; PR #131 Draft; main unchanged.
