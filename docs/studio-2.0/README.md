# Handraw Studio 2.0 · Architecture RFC v1
> Issue #102 · Branch `studio2` · 2026-11-08 · **Contract frozen for P0 integration; endpoint paths are proposals until routed**
>
> Scope: [Web](https://github.com/yang0/handraw-web) + existing [Handraw V3](../generation-works-v3.md). Existing source is still authoritative for operations not yet migrated. This document is a **contract**, not an assertion that all endpoints are implemented.

## 0. Product and constraints

**One Studio · three tasks**: `image` (single/variant), `series` (same-spec, narrative, compare, multi-format), `article` (document and anchored illustrations).
**Two views**: `simple` and `canvas`. `canvas` is a way to edit an existing project, not an independent generation backend. Workflow templates can initialize a new project. History, private library and public work are resources, not task modes.

- All successful Web image generation is public by default through **one logical Run → zero or one Work**, with N successful media displayed as one cover card in feeds. Skill's *local* history is never automatically published.
- User private reference media, private catalog definitions and protected prompt text are **never** made public by publishing a Work.
- No new competing generation, media or public-work truth tables: `generation_runs`, `generation_items`, `media_assets`, `works`, `work_media` from V3 (#84) remain canonical.
- No production legacy data migration is required before launch. Existing local drafts/workflows must not be silently wiped. Preserve `?entry=quick|batch|article|canvas`, `?view=history|workflows`, fork URLs during incremental migration.
- UI must not claim "cloud saved" until server acknowledges a version, and must not claim upstream jobs cancelled when only local waiting was interrupted.

## ADR-01 · Writable authority / simple ↔ canvas safety

| Scope | Writable source | Derived/read-only counterpart |
| --- | --- | --- |
| `Project` | Server project metadata, owner, task kind and active revisions | UI navigation/session caches |
| Simple image / series | Versioned `CreationSpec` and `PlanSlot[]`; every edit is a field-level patch | Compiled Graph, generated prompt, per-node UI |
| Explicit advanced canvas edits | Versioned `WorkflowGraph` with port/node validation and stable IDs | Simple projection with `simple-editable`, `partial-editable`, or `read-only-summary` classification |
| Article body | Versioned `ArticleDocument` with stable `anchorId`s | Article graph nodes and illustration Plan are references, not duplicate body copies |
| Current run | Immutable `RunSnapshot` tied to spec/plan/graph revisions | Live UI state; newer unsaved drafts cannot change queued items |
| Produced file | `ArtifactRef` pointing at owned media ID, RunItem and visible recipe snapshot | Canvas image/card and Work cover |

**Invariant**: At a given revision **one** of Spec/Plan or Graph is the writable execution definition. Changing view never overwrites a complex Graph with regenerated simple nodes. Advanced Graphs with branches/loops are `partial-editable` (safe fields only) or `read-only-summary` on simple view. A successful simple→canvas compilation must be stable/idempotent and preserve existing node/edge IDs. Undo applies only to editor patches, **not** to server-run jobs or publicly recorded Work.

Mutation API (proposed contract): `PATCH /api/studio/projects/{id}/draft` with `baseRevision`, `patch`, and `idempotencyKey`. Server returns `revision` and full effective state or HTTP 409 with current revision; avoid blind last-write-wins. `POST /api/studio/projects/{id}/compile` returns immutable graph revision/hash; only a subsequent execute produces a Run. Existing `/api/studio/workflows` remains in place until matching replacement has tests.

## ADR-02 · Run status, attempts, billing

**Do not confuse three layers.** Current SQLite/PostgreSQL V3 persisted Run enum (in `backend/generation_v3.py`): `pending|uploading|running|partial|success|failed|cancelled`; Item enum: `pending|generating|success|failed|cancelled`. No direct write of `unknown`, `cancel_requested`, `queued` or `submitted` to these CHECK-constrained columns.

1. *Persisted*: Run/Item + `studio_generations` (provider request, idempotency/credits/refund/reconciliation ledger). `generation_items` has unique `(run_id,position)`: a retry attempt is a **new provider execution record**, not a second `generation_items` row.
2. *Client transient*: `submitting`, `cancel_requested`, `checking_remote`, `connection_lost`. Never overwrite backend status.
3. *Presentation*: `queued/running/succeeded/failed/stopped/partial/unknown`, derived from persisted state plus explicit transient flags. A Run-level `partial` cannot prove all slots have terminated.
4. Stable logical identity: `runId`, `slotId` (PlanSlot UUID), `position` (ordered snapshot), `runItemId`, `requestId`/attempt (provider ledger), `idempotencyKey`. `batchId` is one **logical Run**; multiple provider requests are its attempts/items.
5. Repeating the *same request* must not create a second Work or double-charge; explicit **new image variation / re-generation** creates a new Run and may incur a new charge. Retrying a failed attempt may incur fees per actual provider/billing policy; never promise otherwise.
6. Stop means **do not submit pending work** and, where possible, request provider cancel. Accepted provider jobs may still complete and incur charges. Late callbacks must continue to reconcile.
7. Progress invariant: `total = succeeded + failed + cancelled + generating + queued + unknown`; a successful Item requires valid owned `media_id`, not merely an optimistic image DOM or cached count. If materialization is pending, represent explicitly rather than count success.

API (proposed): `POST /api/studio/runs` compiles an authorized immutable snapshot, `GET /api/studio/runs/{id}` returns status plus Items/attempt metadata and media, `POST /api/studio/runs/{id}/cancel-pending`, `POST /api/studio/runs/{id}/items/{slotId}/retry`. Preserve existing /generate, /tasks, batch endpoints until migration is proven. Idempotent, owner-scoped, versioned.

## ADR-03 · Resource vs media permissions

- **CatalogResourceRef**: `{id,type: style|layout|color|tone,version?,source?}`. Display metadata and effective availability checked by the server; private/paid secret prompts assembled on the **server** and not returned via `finalPrompt`/preview/public Work.
- **MediaRef**: `{mediaId,ownerId?,role: character|scene|object|composition|result,source?}`. Personal library images, generated outputs and uploaded docs have owner, storage key and access policy; their URLs are not a substitute for authorization.
- User-selected IDs are not permissions: server checks current entitlement at *each* planning/compile/generation request; invalid/missing IDs are shown as unavailable, **never silently replaced with SC-021 or another fallback**.
- `styleId` is required at **execution**; may be absent before AI-assisted planning. Fusion off means secondary style retained only in draft and not sent to provider. `layoutId` requirement depends on output mode/schema.
- `ratio` is an aspect-ratio declaration, not pixels/resolution; explicit user ratio cannot be overwritten by output-mode defaults.
- Never expose unselected private reference images or authoring secrets through public media detail.

## ADR-04 · Plan / snapshot / Work lifecycle

- `CreationSpec` is globally scoped for a simple project; `PlanSlot` has stable `slotId`, `order`, `overrides` and `lockedFields`; global settings only modify inherited fields. For article, each slot references a stable `anchorId` in a versioned article document.
- Four series kinds: `same-spec`, `story-series`, `compare`, `multi-format`; individual output counts may exceed slot count (six slots × two variants = twelve outputs and cost units).
- AI returns **validated** `SpecPatch` / `PlanPatch`; planning itself never triggers paid generation. Empty plans may be overwritten as reversible drafts. When the user has edits, show diff/revision conflict and preserve locks. `GraphPatch` for advanced canvas is a separate P2 capability.
- Creating a Run captures `schemaVersion`, `projectRevision`, `planRevision`, `graphRevision`, `resourceVersion`, selected slots, effective prompt/media IDs and estimated outputs. The freeze is immutable; later document, plan or graph edits create a new revision.
- A successful Run has at most one public Work with ordered media and one cover. Work visibility is independently moderated. A Project has zero to many Runs; a Run retry does not produce a duplicate Work; a new variation may produce a new Run.
- A `Template` is reusable workflow/Spec structure, not a Run, Work, or container for private media bytes.

## Draft contract (v1)

```text
Project {id, ownerId, kind, title, revision, activeEditorAuthority, draft, graphId?, articleId?}
CreationSpec {schemaVersion,revision,subject,outputMode,style,secondaryStyle?,fusionEnabled,layout?,colors[],tones[],moods[],ratio,ratioSource,referenceMedia[],layoutParams?,lockedFields[]}
Plan {planId,projectId,revision,kind,globalSpec,slots[{slotId,order,subject,layout,style,ratio,referenceMedia,overrides,lockedFields,anchorId?}]}
WorkflowGraph {graphId,projectId,revision,nodes[],edges[],editorLayout}
ArticleDocument {documentId,projectId,revision,markdown,anchors[]}
RunSnapshot {runId,projectId,projectRevision,planRevision?,graphRevision?,outputs[{slotId,position,effectiveSpec}],resources,estimatedOutputCount}
ArtifactRef {mediaId,runId,runItemId,slotId,position,recipeSnapshot,sourceMediaId?}
```

Example request/response (proposal, **not currently deployed**):
```json
{"request":{"method":"PATCH","path":"/api/studio/projects/p1/draft","body":{"baseRevision":3,"idempotencyKey":"edit-4","patch":{"op":"set","path":"/creationSpec/ratio","value":"2.35:1"}}},"response":{"ok":true,"projectId":"p1","revision":4,"saveState":"synced"}}
```
```json
{"request":{"method":"POST","path":"/api/studio/runs","body":{"projectId":"p1","baseRevision":4,"planSlotIds":["slot-1"],"idempotencyKey":"run-p1-5"}},"response":{"ok":true,"runId":"run-5","expectedCount":1,"status":"pending","items":[{"slotId":"slot-1","position":0,"status":"pending"}]}}
```
```json
{"error":{"code":"revision_conflict","requestId":"req-example","message":"草稿已在其他标签更新","currentRevision":5}}
```

**Error taxonomy**: `invalid_spec`, `invalid_resource`, `resource_forbidden`, `invalid_ratio`, `media_forbidden`, `quota_insufficient`, `revision_conflict`, `provider_unavailable`, `upstream_invalid_response`, `remote_state_unknown`; preserve HTTP status/requestId, never return raw provider keys or black-box prompt. Full spec schema and fixtures: [schema](schema.json), [single](fixtures/image.json), [series](fixtures/series.json), [article](fixtures/article.json), [canvas](fixtures/canvas.json).

## Incremental migration / rollout

1. #112: add deterministic tests and fixture-validation to CI, without requiring paid API.
2. #121: pure normalizers/adapters on existing `skill_params`/batch fields, **read-only by default** until round-trip fixtures and permission rules pass.
3. #119: server-owned Run/Item status projection, retries and stop semantics; reuse V3, do not silently change database enum.
4. #122: integrate image/simple form vertical slice, then #123 series and #124 article/canvas while preserving existing entry URLs and data. Never create two writable drafts for the same revision.
5. #128/#108/#109/#129 implement UI against shared view models. #120 advanced DAG and #126 GraphPatch may follow without blocking a usable single-image product.

**Definition of done for #102**: four ADRs, contracts, fixtures, state+permission table and an executable validation test committed. A production migration/PG/S3/real browser run remains separate implementation/verification; this RFC does not falsely claim it.