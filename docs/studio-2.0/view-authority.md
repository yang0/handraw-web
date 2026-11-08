# Studio 2.0 / Issue #107: Project view authority and safe switch

Source: [ADR #102](https://github.com/yang0/handraw-web/issues/102), [Issue #107](https://github.com/yang0/handraw-web/issues/107), [PR #131](https://github.com/yang0/handraw-web/pull/131).

## Authoritative write boundary

| Project authority | Editable source | Canvas execution | Simple view |
| --- | --- | --- | --- |
| spec | CreationSpec and Plan | Stable compiled derived Graph | Fully editable; never write derived Graph independently |
| graph | Same WorkflowGraph | The same Graph | Graph projection only; node-scoped safe patches, no writable Spec duplicate |
| article | ArticleDocument owns markdown/anchors, Spec/Plan owns illustration settings | Derived/linked Graph | Article editor owns text; Canvas never overwrites anchors |

The stable compiler uses Project-scoped IDs and PlanSlot identities. Spec-to-Graph authority transition must be atomic with CAS. Once Graph is authoritative, unverified Graph-to-Spec downgrade is forbidden. A view switch never changes authority.

## Expressibility

- **simple-editable**: one output, unique shared text and style, optional assets/connected loop, no unknown types; existing legacy form edits this same Graph.
- **partial-editable**: multiple outputs sharing text/style or article-linked plans. The present minimal summary exposes only safe common subject editing; branch outputs and other parameters remain Canvas-only. Model projection identifies additional safe candidates for future picker work.
- **read-only-summary**: malformed topology, unknown custom nodes or ambiguous input paths. Display summary, retain all nodes and links, do not create a second blank workflow.

## Patches and revisions

Graph simple-editor patches address a node by stable ID and a whitelisted data field, such as /graph/nodesById/n-text/data/text. The server validates owner, ID uniqueness, topology, field restrictions and Project baseRevision in one transaction. A branch-specific ratio, Run status or edge replacement cannot pass the simple editor patch validator. Complex Graph full replacement remains a Canvas-authority operation, not an ordinary simple parameter patch.

The client compares a confirmed Graph snapshot to the draft. It emits minimal node patches when structurally unchanged; other Canvas edits use the existing Graph-authority save. Offline in-flight payloads/idempotency keys replay unchanged. A 409 preserves the local draft for explicit conflict copy. Server Graph revision advances once per node patch batch; Project revision remains canonical.

## Independent view state

The Project draft stores activeView (canvas/simple) and editorLayout, including camera (vx/vy/vk), selected IDs, panel state, unsaved workflow references and Run/result references. The open/closed local tab stores these alongside the same Project ID/revision/outbox. Group structure stays in Graph. Selected IDs restore only when their nodes still exist. Switching views only changes editor metadata and schedules draft sync for an existing Project. It does not create blank Projects, invoke generation, restart Run, or change billing.

## Evidence and remaining boundaries

Node regression tests: tests/test_studio_view_authority.cjs, tests/test_studio_views.cjs. Server regression tests: tests/test_studio_view_authority.py; existing project/workflow/Run tests remain mandatory. Scenarios include golden image, six-slot series, article anchors, two output branches, ten switches, offline replay, multi-tab CAS and safe patch validation.

Full ArticleDocument/editor migration remains #124; Canvas visual redesign #129; authenticated real-browser multi-tab/offline and remote Run recovery remains #112/#119. This slice is specifically #107 model binding and safe switch, not a claim those other issues are complete.
