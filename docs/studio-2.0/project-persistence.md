# Studio 2.0 · Project Draft Persistence (P0 incremental contract)

Scope: [#103](https://github.com/yang0/handraw-web/issues/103), [#102](https://github.com/yang0/handraw-web/issues/102), [#107](https://github.com/yang0/handraw-web/issues/107). Branch: \`studio2\`. Not a claim that all Studio 2.0 tasks are complete.

## Boundary

- \`studio_projects\`: **private, editable creation drafts** with a server revision and exactly one currently writable authority (\`spec\`, \`graph\`, or \`article\`). Saving a project **does not generate** images, charge credits, publish a work, or create a Run.
- \`studio_workflows\`: reusable workflow templates, still using their own versioned save route. Saving a workflow is not a project save.
- \`generation_runs\`, \`generation_items\`, \`media_assets\`, \`works\`: existing V3 **execution, media and public-work** truth tables; unchanged.
- \`studio_articles\`: existing article editor persistence remains authoritative until #124 moves the article document to the Project contract. **Do not enable a second article-body writer.**
- Current quick/series/canvas editors still edit the existing **Graph in memory**. Consequently their Project integration records \`authority=graph\`, with \`draft.graph\` as the only writable execution definition. This is a deliberately narrow compatibility phase, **not a claim that Spec/Plan has fully replaced the legacy graph engine**. #121/#124 will migrate real Spec/Plan ownership without double writes.

## API

All routes use authenticated web sessions (browser cookies), same-origin write protection and owner-scoped lookups. Tokens without explicit Studio permissions are denied.

| Method | Path | Purpose |
|---|---|---|
| \`POST\` | \`/api/studio/projects\` | Create a private project at revision 1 |
| \`GET\` | \`/api/studio/projects\` | List up to 100 projects, metadata only |
| \`GET\` | \`/api/studio/projects/{id}\` | Read owner project with draft |
| \`PATCH\` | \`/api/studio/projects/{id}/draft\` | Update fields using \`baseRevision\`, CAS, and idempotency |
| \`POST\` | \`/api/studio/projects/{id}/copy\` | Preserve a local conflict as a new owner project ID |

Create:

\`\`\`json
{"projectId":"prj-example-1","kind":"image","authority":"graph","title":"春日海报","draft":{"graph":{"revision":1,"nodes":[],"edges":[]},"activeView":"canvas"},"idempotencyKey":"create-20261108-001"}
\`\`\`

Edit:

\`\`\`json
{"baseRevision":1,"idempotencyKey":"edit-20261108-002","patch":[{"op":"set","path":"/graph/nodes","value":[]},{"op":"set","path":"/activeView","value":"canvas"}]}
\`\`\`

Success:

\`\`\`json
{"ok":true,"projectId":"prj-example-1","revision":2,"saveState":"synced","updatedAt":"2026-11-08T00:00:00.000000Z","unchanged":false}
\`\`\`

HTTP 409 conflict: \`code=project_revision_conflict\`, \`currentRevision\` is included. The server returns **no other user's draft** and never retries with a newer base implicitly. Duplicate delivery with the **same** idempotency key/payload returns the recorded response (\`idempotentReplay=true\`) without another revision. Reusing a key with changed payload returns \`idempotency_key_reused\`.

The patch must use \`op=set|remove\`. Paths are relative to the draft (e.g. \`/creationSpec/subject\`, \`/graph/nodes\`) or project metadata (\`/title\`, \`/authority\`). A Graph-authority project rejects creationSpec/Plan edits; a Spec-authority project rejects Graph edits. Authority can be changed explicitly with an atomic ordered patch. Existing graphs remain untouched when a field is not targeted.

## Client outbox and recovery

The Studio client captures an immutable request with a unique idempotency key. It persists the request, project ID, known server revision and current save state in **account-scoped local tabs**. If the response is lost after a server commit, retrying resends the exact same payload/key. Edits made during upload are not marked saved; they form the next patch after acknowledgement.

Save states: \`local_only\`, \`saving\`, \`synced\`, \`error\`, \`conflict\`. Only \`synced\` means server-confirmed. Unresolved conflicts block auto-retry; clicking “项目冲突 · 保留副本” creates a **new** Project with local content and leaves the remote project unchanged. Failed copy responses are also replay-safe and keep their new ID/key on refresh.

Saving is debounced; switching tabs flushes unsynced active edits. On reconnect and reload, a pending outbox can resume. The current Studio uses the local-tab restore path for opening recent work. A full cross-device Project Center UI and project restore picker belongs to #106 and remains pending.

## Validation and constraints

- All queries are account-scoped; querying another user's project is indistinguishable from a missing project (404).
- Media references with \`mediaId\`/\`sourceMediaId\` require matching \`media_assets.owner_user_id\`. Other catalog resource entitlements still require validation at *execution* (#105).
- Inline \`data:image/\` and large embedded media must be uploaded as private assets first; cloud save fails clearly without erasing the local draft.
- Store at most 512 KiB of JSON per project; prevent embedded API keys, black-box prompt secrets and invalid patch paths.
- This is additive SQLite migration **101**; fresh PostgreSQL staging derives schema via \`ops/bootstrap_postgres_v3.py\`. Existing PG instances require a separately reviewed additive schema rollout, **not** re-bootstrap or database deletion.

## Verification

- \`tests/test_studio_projects.py\`: migration, CAS, idempotency, owner isolation, graph/spec authority, media references, conflict copy, no generation side effects.
- \`tests/test_studio_project_http.py\`: actual HTTP handler with cookies, PATCH, CSRF, copy and permissions.
- \`tests/test_studio_project_sync.cjs\`: frozen client outbox, lost response, in-flight edit and copy.
- \`tests/test_studio_workflow_autosave.cjs\`: existing template save remains a separate flow.
- Full Python tests and Node checks remain CI gates; a real browser and live PostgreSQL write/read E2E are **not** implied by passing mocks and service-level tests.

## Remaining before #103 can close

1. Restore projects from any signed-in device through an integrated Project Center (#106), including conflict diff UI and project deletion/archival.
2. Migrate quick/series to authoritative Spec/Plan, and article to a single ArticleDocument writer; ensure no competing writable Graph or article state (#121/#124).
3. Real browser E2E: offline, second tab, refresh, account switch, close tab, private uploads, generation in progress; measure any autosave-induced render/focus regressions.
4. Live PostgreSQL migration plan for existing instances and storage-limit/operator observability.
