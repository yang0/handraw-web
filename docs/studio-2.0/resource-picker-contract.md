# Studio 2.0 Resource Picker / CreationSpec contract — Issue #105

Branch: \`studio2\`. Related: #102 (ADR-03), #103 (Project CAS), #118/#121 (adapter), #122/#123 (Make Image/Series), #124 (Article), #95 (click failures).

## One contract, existing UI

Existing Canvas skill-parameter picker and the Make Image and Batch cards call the same \`openSkillFieldPickerModal()\` picker. The selector now validates and emits a canonical **DirectoryResourceRef** in addition to the legacy ID. Asset selection retains the existing three-tab modal (My Gallery / Official Samples / Upload). Its confirmed owner-only media identity is a **MediaRef** and is deliberately *not* a DirectoryResourceRef.

No duplicated private upload table, prompt engine or independently writable Spec/Graph state was added.

\`\`\`json
{
  "style": {"id":"FA-001","type":"style","source":"official","version":1},
  "secondaryStyle": {"id":"FA-002","type":"style","source":"official","version":"current"},
  "fusionEnabled": false,
  "layout": {"id":"SC-021","type":"layout","source":"official","version":1},
  "colors": [{"id":"C-01","type":"color","source":"official","version":1}],
  "tones": [{"id":"T-01","type":"tone","source":"official","version":1}],
  "referenceMedia": [{"mediaId":"<owner-only-assetUid>","role":"scene"}]
}
\`\`\`

- \`id\`: stable catalog code; \`type\`: style/layout/color/tone; \`source\`: official/community/override/private/pending/exclusive; \`version\`: catalog revision when explicitly provided, otherwise \`current\`. **"current" is NOT an immutable historical snapshot**; the server always re-resolves it before accepting a Project draft.
- Only when \`fusionEnabled=true\` does an execution spec require and validate \`secondaryStyle\`. When false, a previously selected secondary style is preserved in the draft but not applied to a run.
- A private reference is \`{mediaId,role}\`. \`mediaId\` identifies a generated \`media_assets.id\` owned by the user, or an undeleted private-gallery \`user_uploads.asset_uid\`. A gallery upload's old \`user_uploads.id\`, local \`File\`/blob URL and public/official preview image URL are **not** media capabilities. Local images stay in local Graph state until upload.
- Resource definitions and especially protected black-box prompts are **never** included in ResourceRef.

## Where data lives

During the Graph-authority compatibility phase (#121/#124 incomplete), \`skill_params.data.style1/style2/layout/colors/tones\` remain the execution source, while \`skill_params.data.resourceRefs\` stores the canonical identity metadata within **that same node**:

\`\`\`json
{
  "type":"skill_params",
  "data":{
    "style1":"FA-001","layout":"SC-021","colors":["C-01"],"tones":[],
    "resourceRefs":{
      "style":{"id":"FA-001","type":"style","source":"official","version":"current"},
      "layout":{"id":"SC-021","type":"layout","source":"official","version":"current"},
      "colors":[{"id":"C-01","type":"color","source":"official","version":"current"}],
      "tones":[]
    }
  }
}
\`\`\`

Batch rows can carry \`layoutRef\` alongside \`layout\` when a per-slot picker returns a verified layout. All of these fields are persisted in \`Project.draft.graph\`, under Project \`authority=graph\` and the existing \`baseRevision\` CAS. \`studio-core.js.normalizeLegacyParts()\` projects them into CreationSpec for display/validation without becoming a second writer; \`applyLegacySpec()\` can round-trip them back into the same legacy node. A Spec-authority Project stores \`Project.draft.creationSpec\` instead and is validated by the same server helper.

## Trust boundary

1. The browser validates the selected ID/type/source/version from its loaded catalog and permission hints. A locked or nonexistent resource is explicitly rejected in the Picker; Random cannot bypass the same check.
2. Immediately before a Graph generation, the active control's resolved style/layout/color/tone plus loop style/layout overrides are checked. Invalid choices remain visible so users can correct them; no automatic fallback or speculative AI IDs.
3. **Server authority:** \`backend/studio_resources.py\` validates Project create/PATCH in the same database transaction as the CAS write. Style/layout use the existing \`resource_registry.resolve(...,purpose="generate")\` for private owner, published status and unlock checks. Official colors and tones use the catalog ID sets. Typed Graph refs must exactly match their legacy selected IDs. Server rejects invalid \`source\`/version, not simply coercing them.
4. Private MediaRefs are rechecked against either \`media_assets.owner_user_id\` or undeleted \`user_uploads.asset_uid/user_id\`. Deleting private media or switching accounts invalidates access even if a stale browser still displays an image.
5. Projects and reference-media owner authorization are **not** inferred from Work's public visibility. Public gallery output does not make uploaded reference images public.
6. Incomplete old drafts with only legacy string IDs remain readable and editable. Their invalid IDs are not erased or upgraded into invented official refs; execution preflight blocks them. A selected trusted ref cannot disagree with the corresponding Graph ID.

## Errors & scope

\`invalid_resource_ref\`, \`resource_type_mismatch\`, \`resource_not_found\`, \`resource_forbidden\` (403), \`invalid_resource_source\`, \`resource_source_mismatch\`, \`invalid_resource_version\`, \`resource_version_conflict\` (409), \`resource_ref_mismatch\`, \`project_media_forbidden\` (403), \`project_media_upload_required\`. Failed Project saves retain local drafts and the idempotent outbox; confirmed remote CAS is never silently overwritten.

The Project validator accepts partial draft CreationSpecs (e.g. a newly created blank project) but the **execution** validator requires a subject/valid mode/style. This is intentional: invalid or incomplete drafts may be preserved without paying for a generation.

## Verification

- Node: \`tests/test_studio_resources.cjs\` + existing \`test_studio_picker_interactions.cjs\`, \`test_studio_core.cjs\` and full app syntax/checks.
- Python: \`tests/test_studio_resource_refs.py\`, \`test_studio_projects.py\`, real HTTP Project contracts, existing production-storage checks.
- CI checks run on \`studio2\` draft PR #131.

**Still open under #105/#124:** live authenticated browser picker flows (keyboard, small screen, IME, modal close/reopen); actual Article editor's own style/layout controls mapped into this shared picker; all legacy direct preset/mood paths and fine-grained catalog definition revision pinning. The PR must stay Draft until these and the broader Studio2 integration criteria are satisfied.
