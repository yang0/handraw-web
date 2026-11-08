# Studio 2.0 · Issue #122 — Make Image Vertical Slice

Repository: https://github.com/yang0/handraw-web
Target: studio2 / Draft PR #131; base Issue #121 (normalization); Issue #118 (vertical-slice coordination).
Other dependencies: #100 selected-image fork, #105 resource picker, #104/#119 V3 Run, #112 browser QA.

## Single-writer contract

The simple Make Image form now reads/writes the same Project Graph nodes as canvas. No second creation-spec store exists. The additional pure module demo/assets/studio-quick-spec.js consumes studio-core.js and studio-normalization.js from #121 and studio-resources.js from #105.

- read(parts): canonical CreationSpec view of skill_params, text_input, output_control, asset.
- apply(parts, field-level changes, catalog): validate patch, catalog identity/type/source/version, and lockedFields before changing any data. Write only affected node fields and resourceRefs; do not replace unrelated node keys, edges, reference assets, or output history.
- setAssets: keep original multi-reference asset.items, including local-only images. Private MediaRefs are not minted from blob URLs or previews.
- fork: selected media-specific draft from Issue #100; author and work/media source attribution remains owned by studio-app.js. No cover-first substitution.
- preflight: subject/mandatory style, valid ratio, current catalog availability and entitlement. Fail before any requestId or billable submission. Server still rechecks permissions at reservation.
- capture: deep-clone the effective spec and Graph at the current project revision. Disabled fusion retains secondary style in draft but sets it to null in execution spec.
- projectRun: V3 persisted Run/Item statuses only. Success requires an owned mediaId and an available imageUrl; an optimistic DOM image or old local boolean status is not proof of completion.

Core Make Image UI binds actual controls to apply(): theme, style1/style2, layout, colors/tones, mood/customMood, ratio, mode, whitespace, audience/business scene, SC-021 selection type, SC-022 name/pinyin. Explicit ratio remains set across graphic-text/pure/poster mode changes, including unusual ratios such as 2.35:1. The shared Picker forwards full verified ResourceRef and preserves source/version. AI-assisted plan is validated through the adapter instead of bypassing locks.

## Frozen execution vs ongoing draft

When the existing output-control runner receives a valid action, it clones the entire Graph before the async work and compiles its plan and both prompt modes against this single executionGraph. Changes to the current Graph cannot modify already accepted requests. The existing studio-prompt-engine.js remains the only frontend prompt compiler; server-side protected recipe text stays on the server and is never placed into this new adapter.

The V3 generation reservation response now includes an owner-scoped opaque runId; it is not the same thing as genId/requestId or a guessed batch hash. The output node persists runId and pending request IDs. The Make Image view fetches GET /api/studio/runs/{runId} (owner-only), computes RunProjection via studio-core.js and uses it for completed count, failure count, remote-busy and confirmed result media. Server state is the single truth for success. If Run cannot yet be queried, visible local results are labeled local and no cancellation/refund is presumed.

Stop only aborts local waiting and blocks pending submissions. Accepted provider attempts may still finish and incur charges. The form only shows Stop while this page owns the live controller; after reload, the server Run can remain running, with pending IDs intact, but the ghost local busy flag is cleared. Retry of a failed terminal slot explicitly starts a new gateway attempt tied to the same logical batch (existing V3 rules), invalidates any cached terminal RunProjection, and never promises a free retry. Both the main Run button and the "another image" action block duplicate submission while the server Run is active.

## Regression and rollback

CI gates:
- tests/test_studio_make_image_integration.cjs: true UI handler simulation, atomic node patches, graph siblings/assets, explicit ratio/fusion, SC-021/022, unusable resources, Run success/error/unknown/stop projection, selected-media fork, stable frozen snapshot, script order.
- tests/test_studio_quick_run_contract.py: server Run identity, owner filter and failure to fabricate missing IDs.
- Existing tests/test_studio_make_image.cjs, test_quick_stale_generation.cjs, test_work_fork_hydration.cjs, test_studio_picker_interactions.cjs and test_batch_stop.cjs plus full Python suite.

New code is additive and can be rolled back by removing the studio-quick-spec.js script and disabling its app bridge, leaving original Graph drafts and existing Project/Run tables unchanged. No database migration or duplicate prompt engine was introduced.

Unverified / deferred to #112/#119: authenticated full-browser Playwright E2E against a running gateway, actual paid image generation and refund reconciliation, PostgreSQL + object-storage real deployment, comprehensive immutable server RunSnapshot binding to Project revision. CI mock/unit/integration passing alone is not evidence of these external stages.
