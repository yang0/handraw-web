# Studio 2.0 · Issue #121 — Normalization Core and Golden Fixtures

Repository: https://github.com/yang0/handraw-web. Branch: studio2. Related ADR #102, Resource Picker #105, Views #107, Draft PR #131.

## One writable authority

| Project authority | Writable source | Projection, never another writable copy |
| --- | --- | --- |
| spec | CreationSpec and Plan | compiled Graph (derived) |
| graph | WorkflowGraph | derived Spec/Plan summary and safe node-local patches |
| article | ArticleDocument markdown and anchors, plus illustration Spec/Plan | linked Graph references, never a second markdown |

The pure adapter in demo/assets/studio-normalization.js has no generation, database, network, or prompt-assembly capability. It does not mutate the caller input. normalizeDocument returns wire (persistable truth), projection (read-only transient state), writable roots, validation and warnings. serializeDocument saves wire only, not projection; it refuses secret prompt and credential fields. The original graph remains authoritative when Project.authority is graph; preexisting read-only Spec snapshots may be preserved for compatibility but are not writable.

## Consumption contract

The browser global is window.HandrawStudioNormalization; the Node CommonJS entry is demo/assets/studio-normalization.js. It delegates to existing studio-core.js, studio-resources.js and studio-views.js:

- normalizeSpec(raw): read typed ResourceRefs; supply safe defaults for fields absent from legacy drafts. If an invalid field is present, keep its raw value for repair instead of silently selecting an official resource.
- normalizeLegacyGraph(graph, options): clone and project legacy skill_params, text_input, output_control, asset and loop. Returns the original user graph with migrated slot IDs pinned on the clone. This never becomes a second execution source.
- normalizePlan(plan, article?): require unique stable slot IDs, validated order and article anchor/revision, while keeping overrides, media and locks.
- normalizeDocument(wire,{strict}), serializeDocument(model), reload(json): normalize → serialize → reload → normalize; strict mode reports schema conflicts. This is a pure canonical JSON wire contract.
- patchDocument(model,patch,baseRevision): optimistic Project revision and authority checks; fields under /creationSpec and /plan/slotsById/{slotId}/overrides/{field}, never /plan/slots/{index}; node patches delegate to #107. User and per-slot locks prevent unauthorized AI override.
- validateForExecution(spec,{catalog,verifyMediaOwner}), executionSpec(spec,slot,options): hard-fail for missing directory, missing/locked/wrong-type/wrong-version styles/layouts, unavailable private images, or invalid references. All rights are rechecked server-side before persistence and execution. A secondary style remains in the draft when fusion is off, but the effective execution copy explicitly excludes it.

No new prompt compiler is created: the existing demo/assets/studio-prompt-engine.js and authorized server recipe pipeline remain the sole prompt construction path. Black-box recipe text is not a serialized ResourceRef.

## Legacy field mapping and ratio provenance

Legacy skill_params.style1/style2/fusion/layout/colors/tones/moods/customMood/whitespace/audience/businessScene/sc021Type/sc022Name/sc022Pinyin; text_input.text; output_control.mode/ratio/ratioSource; and asset.items map into the documented CreationSpec fields. ResourceRef stores catalog identity and optional source/version; AssetRef/MediaRef stores owned mediaId and role, never catalog type. Media preflight is separate from directory authorization.

No preview URL, raw local File, upload-row ID or public Work grants private-media ownership. Local asset.items stay in the legacy Graph until upload confirmation. Missing/deleted resource IDs are shown as errors and retained as identities, never substituted with an unrelated official placeholder.

An explicit user ratio edit sets ratioSource=user, even if numerically equal to a mode default; a mode change updates the default only when the ratio was not explicitly set. Ratio describes aspect, not output resolution. For pre-v1 drafts, a non-default ratio with no source is inferred as user input.

## Stable PlanSlot identity and article links

- Fixed promptListText and AI batchRows both project to PlanSlot objects with slotId, order, subject, overrides, lockedFields, referenceMedia and optional anchorId.
- If the old workflow had no IDs, the first import creates deterministic IDs based on plan identity plus original content/position to disambiguate duplicates. These are **migration seeds, not logical array index IDs**. The adapter pins them on a cloned Graph as studio2SlotIds; later edits/reorder preserve these IDs. Persist the clone before replanning. New AI entries with their own slotId are not silently relabeled as old rows.
- A slot's locked layout or subject cannot be overwritten by AI; per-slot private images and unknown legacy metadata survive replan. Duplicate IDs abort normalization.
- An article Plan preserves documentId, documentRevision, and stable anchorId. A stale document revision, missing anchor or duplicated anchors is a schema error; no index-to-anchor fallback.

## Four golden fixture families

- docs/studio-2.0/golden/image.json: explicit 2.35:1, fusion disabled with retained second style, SC-021/022 parameters, catalog source/version, private and local-only references.
- docs/studio-2.0/golden/series.json: six fixed and six AI-generated slots, stable IDs, slot locks, different layout, private reference and anchor.
- docs/studio-2.0/golden/article.json: article document revision and two stable anchor IDs mapped to cover/inline PlanSlots.
- docs/studio-2.0/golden/canvas.json: double output branch, custom node/edge, group, Run result refs, and private media. It remains read-only in simple projection.

Tests: tests/test_studio_normalization.cjs (full golden roundtrip, legacy inverse mapping, CAS, resource/media preflight and lock cases); tests/test_studio_plan_slot_access.py (real Project persistence rights); existing studio_core/resources/project/run regression. These are CI gates, with no paid gateway calls.

## Migration and rollback

Dual read, single authoritative writer. Never automatically delete or destructively upgrade original local workflows. A cloned migrated Graph and pinned IDs are only written after an explicit Project save with a server-confirmed revision. Offline save failure or CAS conflict keeps original draft/outbox and allows explicit conflict copy. Disabling the consumer reopens old Graph JSON; no DB migration is introduced.

Not in #121: UI rework, full Article editor integration (#124), image/series UI wiring (#122/#123), Run state changes (#119), real browser E2E (#112).
