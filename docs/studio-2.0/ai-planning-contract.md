# Studio 2.0 — Authorized AI planning protocol (Issue #125)

Repository: https://github.com/yang0/handraw-web · Branch: `studio2` · ADR #102, #105, #107, #109, #121 and #124.

## Single contract, three entry points

`POST /api/studio/ai-plan` is an authenticated, **proposal-only** endpoint used by Make Image, Series/Batch and Article editor. Each entry sends `kind: "image" | "series" | "article"`, `subject`, `baseRevision` (nonnegative integer) and optionally `projectId` (server CAS), `planRevision`, `count`, `lockedFields`, sanitized current resource IDs and PlanSlot IDs; article sends public summaries of real paragraph blocks `{idx, kind, text, anchorId}`. The endpoint accepts neither media publishing grants nor charged generation flags.

The server queries the **entire** currently available directory (official/static, catalog DB, user-owned published or pending resources where entitled). Every ID is re-resolved with `resource_registry.resolve(viewer=user,purpose="generate")`. Access filtering happens **before** prompting; only ID, display name, public purpose/description and type/source are sent to the model. No definition, protected prompt, secret blackbox text, private media references, source files or API keys leave this boundary. The complete entitled directory is supplied; display candidates are a short, theme-ranked subset, never an unexplained fixed prefix.

The model is instructed to return exactly a JSON object with `styleId`, `layoutId`, `ratio`, `reasons: {style,layout,ratio}` and `slots`. The parser unwraps an optional whole-message `<escape>` wrapper or `\`\`\`json` fence; **arbitrary prose containing JSON is not accepted**. Missing keys, unknown keys, unauthorized or unknown IDs, bad ratio, insufficient slots and invalid document anchors are errors, **not defaults**.

Success response is intentionally not an executable Run or an applied draft:

```json
{
  "ok": true, "schemaVersion": 1, "kind": "series", "source": "model",
  "phase": "review", "baseRevision": 7,
  "creationSpecPatch": {
    "baseRevision": 7,
    "changes": {
      "style": {"id": "FA-002", "type": "style", "source": "official", "version": 1},
      "layout": {"id": "SC-022", "type": "layout", "source": "official", "version": 1},
      "ratio": "3:4"
    },
    "reasons": {"style": "…", "layout": "…", "ratio": "…"},
    "candidates": {"style": [], "layout": []}
  },
  "planPatch": {
    "baseRevision": 2, "kind": "story-series",
    "slots": [{"slotId": "slot-stable", "order": 0, "subject": "…",
      "overrides": {"layout": {"id": "SC-022", "type": "layout", "source": "official", "version": 1},
                    "ratio": "3:4"},
      "reasons": {"subject": "…", "layout": "…", "ratio": "…"}}]
  },
  "cost": {"generationStarted": false, "runCreated": false}
}
```

For `image`, `planPatch=null`. For `article`, each slot also has an immutable `anchorId` derived from the *original request* (not model text); the cover uses `afterBlockIdx=-1` and `anchorId="cover"`, and subsequent slots use unique real block indices. An article planning reply never modifies ArticleDocument markdown. Existing slot IDs are preserved; extra previously created cards, images, private references, completed Run/Item identifiers, manual subject, locks and customized prompts survive application.

## Authority / conflict policy

1. Snapshot the editor's CreationSpec and Plan revisions, source graph/draft signature and, for article, the actual document body, title and paragraph/slot anchors.
2. Request a structured plan. Display phase messages for lookup, model inference, schema/permission validation and conflict review. The response is not applied automatically until local checks pass.
3. Revalidate resources with the same Studio picker rules, independently of the server's check. Compare every proposed field. A user lock **always wins**. A manual override is retained unless the user opts into that specific conflict; no broad "unlock everything" action exists.
4. Stage Spec and Plan on detached copies. Reject if source revision/signature changed; commit only validated node fields and stable PlanSlot payloads. Never replace a complex WorkflowGraph or another node's typed ports/links.
5. Return an undo token containing the exact prior state and resulting signature. Undo refuses if a subsequent manual edit occurred; a successful undo is a **new edit with monotonic revision**, not rollback of a CAS counter.
6. Production Project saves use #107's optimistic concurrency; the server checks `projectId/baseRevision` before and after inference (when supplied). For unsaved local drafts, the client retains an exact snapshot and rejects stale responses before mutation.

## Error taxonomy

| Code | Meaning |
| --- | --- |
| `ai_upstream_502` | Gateway specifically returned HTTP 502 |
| `ai_not_configured`, `ai_timeout`, `ai_unavailable` | Missing configured gateway, timed out or other upstream failure |
| `ai_invalid_json` | Gateway envelope or model body not valid JSON |
| `ai_schema_invalid` | JSON structure/ratio/slot type missing or invalid |
| `ai_resource_not_found`, `ai_resource_forbidden` | Unknown/expired resource vs known but unauthorized |
| `ai_catalog_empty`, `ai_cannot_recommend` | No eligible directory resources vs no complete recommendations |
| `ai_anchor_invalid` | Model referenced an invalid or duplicate article paragraph anchor |
| `ai_revision_conflict`, `ai_plan_revision_conflict`, `ai_undo_conflict` | Draft changed during planning, Plan changed or undo is no longer safe |
| `token_disallowed`, `rate_limited` | Unsupported token auth or reached the planning-only daily rate limit |

No code path in this protocol calls `/api/studio/generate`, creates `generation_runs`/`generation_items`, creates `works`, reserves generation credits or auto-publishes assets. `consume_daily_usage(..., "studio_ai_plan")` limits *planning calls only* and is not image-generation billing.

## Compatibility, boundaries and verification

Legacy image/batch/article endpoints remain available to avoid breaking older clients, but the three Studio 2.0 entry points use `/api/studio/ai-plan`. Graph topology mutation is #126; this issue modifies only safe Spec/Plan fields. Article import/export remains #109. Regression gates: `tests/test_studio_ai_plan.py`, `tests/test_studio_ai_plan.cjs` and `tests/test_studio_ai_plan_http.py`, plus existing #105/#107/#121/#122/#123/#124 regression suites. Mock gateway fixtures do not use any paid external API.
