# Studio 2.0 · Project Center / Cross-device Recovery (Issue #106)

## Scope

A single Project Center at /studio/?view=projects exposes cloud-saved Projects and account-scoped local drafts with distinct save states. It does not replace generation history, the workflow template library, the article editor, or the V3 Run/Work ledger.

Navigation presents 图片创作 / 系列创作 / 文章配图, an explicit 简洁编辑 / 画布 switch, then 项目中心 / 生图历史 / 工作流 as separate destinations. Existing entry=quick|batch|article|canvas, view=history|workflows, and fork/prefill links retain their original routes.

The Project Center calls GET /api/studio/projects?q={text}&limit=40&cursor={token} and GET /api/studio/projects/{id} using authenticated web sessions. The list API applies an owner predicate, literal-escaped title search and a stable (updatedAt,id) cursor; the response includes nextCursor/hasMore. The UI loads pages on demand and debounces server search so it does not silently miss projects after the first page. The rendering contract resides in demo/assets/studio-project-center.js; remote project text is escaped rather than interpolated as trusted HTML. The Studio router and state owner remain demo/assets/studio-app.js.

A ?project={id} URL deep-links to a project. Cloud drafts whose authority is graph can be restored into a supported canvas or simple editor. Spec/article authority drafts show 待编辑器接入 until #121/#124 provide the corresponding single-writer editor. No flattening to a legacy Graph is allowed.

## Restore decisions

1. If a matching open project has unsynced local edits, activate the local tab without applying any remote payload.
2. If a tab was closed in local_only, saving, error or conflict state, archive the full graph, known revision and pending idempotency request under the current account's scoped local storage key. Show it in Project Center, and restore it before attempting a cloud fetch.
3. If the same confirmed cloud revision is already open, activate that tab rather than creating a duplicate.
4. If a confirmed local revision is older than the server and no unsynced edits exist, explicit Continue Editing can restore the newer server graph.
5. Network/authorization failure does not claim cloud save success; the user can retry and local drafts remain visible.
6. A project fetch started under account A is ignored if the user changes accounts. If the user navigates away while a project is being fetched, the response must not redirect unexpectedly.

A tab with unsynced changes is not removed until a complete recovery copy has been successfully stored. QuotaExceededError blocks close and shows an explicit warning; there is no hard cap that silently evicts an older unsynced backup. The archive is scoped to the current account.

## New project entry

- 图片创作 creates a new empty three-node Graph and enters quick editor.
- 系列创作 creates a new six-edge batch Graph with a blank plan and enters series editor.
- 文章配图 delegates to the existing single-writer article editor, not a second parallel article Project save.
- 从工作流开始 delegates to the existing template import/library page.

A new project is persisted to cloud only after the first edit or an explicit save, not simply by entering the empty-state UI.

## Verification

- tests/test_studio_project_center.cjs covers escaping, navigation, empty state, cloud restoration, local conflict precedence, account isolation, and task entry.
- tests/test_studio_closed_project.cjs covers frozen idempotency request recovery, archive quota protection, no eviction, and synced-tab handling.
- Existing Project CAS HTTP/server/client tests remain in the CI gate.
- tests/test_studio_project_pagination.py covers 113 projects, literal search with percent/underscore, cursor ordering and owner separation. HTTP and transport tests cover encoded query/cursor values.


These automated tests are not a substitute for actual signed-in browser screenshots or multi-tab network/offline acceptance tests.

## Known gaps

- Cloud Project Center lists only the 100 most recent projects. Pagination and server-side search remain P1.
- Article and true Spec/Plan authority will be activated only after #121/#124 connect their single authoritative writers.
- Browser-local storage can be erased by the browser or private-browsing session; only a server-acknowledged cloud save is durable across devices.
- Real-browser 360px/768px/1280px visual review, keyboard navigation, copy/paste, touch and multi-tab concurrency E2E remain necessary under #112.
