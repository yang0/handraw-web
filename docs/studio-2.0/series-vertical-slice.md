# Studio 2.0 · Issue #123 — Series / Batch Vertical Slice

Repository: https://github.com/yang0/handraw-web  
Integration branch: studio2 · PR #131 (Draft)  
Parents and dependencies: #118, #121 (CreationSpec/PlanSlot core), #122 (Make Image), #110 (structured AI PlanPatch), #119 (V3 run), #112 (browser QA).

## Authority and migration

A single existing **Loop node** owns its canonical \`data.studio2Plan\` object. Every slot has:

- \`slotId\` — stable identity; neither row index nor mutable title is a primary key.
- \`order\` — user-reorderable presentation and candidate dispatch sequence.
- \`subject\` — per-image theme.
- \`overrides\` — individually authorized ResourceRefs for style, secondaryStyle, layout, plus ratio.
- \`referenceMedia\`, \`skipGlobalRefs\` — per-image multi-reference images and global/local merging rules.
- \`lockedFields\`, \`userOverrides\` — prevent AI replan from clobbering explicit human edits.
- \`suggestedLayout\` — AI recommendation remembered while Fixed mode temporarily inherits global layout.

\`demo/assets/studio-series-plan.js\` is the only series plan adapter. \`promptListText\`, \`batchRows\`, \`studio2SlotIds\` are now **read-only compatibility mirrors** derived through \`sync\`, and are never an independently editable second plan. A one-time importer rehydrates older fixed-line or AI-row projects, including hidden AI overrides saved while in fixed mode. Cross-refresh \`studio2Plan\` survives via the same Graph/Project persistence as all other studio nodes. No database schema change.

Atomic field-level \`patchSlot\` uses optimistic \`plan.revision\`, catalog ResourceRef source/version validation, and field locks. Both planning strategies use the *same* ordered PlanSlot array; switching Fixed ↔ AI never resets IDs, references, order, locks, or prior outputs. \`mergeAI\` keeps manual/locked fields, allowing future #110 PlanPatch to update only unlocked fields.

## Output expansion and billing contract

**Plan slots are not billable outputs.** For 6 slots × 2 candidate images there are 12 distinct physical requests. Each frozen output carries \`{slotId,slotOrder,candidateIndex,outputIndex,outputId}\` where \`outputId = slotId + ":candidate:" + candidateIndex\`.

- The server's flat \`batchIndex\` always equals frozen \`outputIndex\` (0–11), and \`batchTotal\` equals 12, not six. Its V3 \`generation_items.position\` uses \`batchIndex * 1000\`; returned \`slotIndex\` is that flat output index. The client maps this back to the frozen slot/candidate identity.
- The existing bounded asynchronous queue preserves per-output idempotent \`requestId\`, and reports out-of-order success/failure in the correct physical slot without changing stable identity.
- **One logical \`batchId\` → one V3 Run → one public Work.** A retry targets the original failed \`outputIndex\` from the frozen snapshot, and does not regenerate or overwrite successful outputs. No new gallery Work is introduced by an individual retry.
- Before async prompt compilation, the execution graph is cloned; on retry the original frozen snapshot is reused, not the newer editable plan. The cloned payload strips previous RunSnapshot references and output-gallery data to prevent size blowups. UI progress remains a read projection, not a competing database.
- Preflight validates every effective CreationSpec and the selected catalog resources. Private/generated reference images are owner-resolved **before any quota/credit reservation**, with invalid, expired or inaccessible images rejected explicitly. The server remains the final authority.

## UI and lifecycle

\`studio-batch.js\` reads the canonical Loop PlanSlot. The AI row table and fixed multiline form both patch it; per-row buttons allow editing theme, independent style/layout/ratio/references, locking, duplicating, reordering and removal. The candidate selector multiplies actual output count (max 200). The cost and confirmation labels use actual outputs. The table shows independent candidate outcomes and retry buttons with *physical* output IDs.

\`studio-app.js\` retrieves \`GET /api/studio/runs/{runId}\` (authenticated owner only), projects it with \`Core.selectRunProjection\` and \`Series.project\`, and renders status/result images from V3 \`Run/RunItems\`. Success requires owned \`mediaId\` plus stored URL; a local image or stale \`completedCount\` is not a paid-success confirmation. If a user reorders the editable plan after starting a Run, previous results still attach via original **slotId**, never the new row index. Out-of-order callbacks and duplicate response references are de-duplicated.

Stop aborts only unsent/local work. Requests already accepted by the upstream gateway may continue and charge; the UI does not falsely claim cancellation/refund. Network-unknown jobs preserve cloud request IDs across refresh/restart; new submissions are blocked while unresolved remote jobs exist. Failed output retries require a confirmed V3 terminal failure and invalidate cached terminal Run projection.

## Tests and unverified real-world stages

- \`tests/test_studio_series_plan_integration.cjs\`: 6 stable IDs, slot3 manual overrides/locks, fixed↔AI roundtrip, LCS paste insertion, row clone/reorder, old AI-row importer, 6×2 outputs, frozen graph/candidate identity, duplicate/out-of-order Run projection, one-slot retry, real existing prompt engine, UI script order.
- \`tests/test_studio_series_run_contract.py\`: real database V3 12-output logical Run, 3 success + 2 failure + 1 running, owner-scoped read, retry only physical position3, idempotent media links, exactly one Work.
- \`tests/test_studio_series_reference_preflight.py\`: owner-scoped pre-billing references, deleted/other-user images, count/format invalid; no silent reference dropping.
- Existing #121/#122 and all other Node/Python/regression jobs remain in CI; no second prompt compiler or Run state machine.

**Do not claim** a live browser full-flow, real paid generation, refunded external gateway attempt, production PostgreSQL/object storage, or high-load six-request concurrency were verified solely by unit/CI tests. Browser/gateway acceptance belongs to #112/#119, including reopen/reload in an authenticated environment.

Rollback: remove the \`studio-series-plan.js\` script and batch/app bridges and restore prior legacy import; existing Loop nodes, Project data, gallery Run tables and other modules stay unchanged. Keep backups of v2 PlanSlots when reverting to v1.
