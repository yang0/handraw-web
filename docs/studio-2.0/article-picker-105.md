# Studio 2.0 · Issue #105 Article Picker / CreationSpec contract

Target: `studio2-issue105-ci`, Draft PR #131. Four entry points—Make Image, Series, Article, Canvas—reuse the existing `openSkillFieldPickerModal` and `openAssetPickerModal`, with `HandrawStudioResources.resolveSelection` and `mediaRefFromAsset`. No duplicate frontend catalog/entitlement engine, prompt engine, or generation backend is introduced.

## Writable authority and persisted references

- ArticleDocument owns Markdown, stable anchors, and the article's illustration CreationSpec. `HandrawStudioArticle109.snapshot()` serializes `styleRef`, `layoutRef` (each id/type/source/version) and verified private `referenceMedia` into the same Project with `authority=article`.
- The current Article editor is a draft projection; selecting a style, layout, or owned reference calls the existing `syncArticleEditorDraftToHistory` + `markArticleProjectChanged` + Project CAS autosave. The server independently checks directory entitlements and ownership on Project writes. A 409 preserves local draft and never silently overwrites a newer version.
- Historic article drafts with only `styleId` / `layoutId` remain readable. Their ID is never retroactively treated as an owned or version-pinned definition; server revalidates before accepting a new Project version.
- The authenticated My Gallery response's `mediaId` or `assetUid` (not an image URL, uploader local row ID, or `File`) is the only valid private MediaRef. Official sample previews remain local items and cannot pretend to be owned private media.

## Unified UI

- Article's style `#editor-style-picker` and new layout `#editor-layout-picker` call `openSkillFieldPickerModal` with typed `onPick(id,ref)`, current selection, inherited catalog grouping/search/favourites/unlocks and Enter/Space keyboard activation.
- Article's new `#editor-reference-picker` reuses `openAssetPickerModal` (My Gallery / Official Samples / Upload). Selection returns verified private MediaRefs and safe official previews. Missing/private-unconfirmed references are rejected rather than silently assigned a fictitious identity.
- Canvas, Make Image, Series retain existing picker adapters and DOM/events. Any missing/deleted/unauthorized catalog ID is shown as a repairable error and does not trigger a billable request.
- On execute, Article checks both resource types and private MediaRef shape *before* payment confirmation; backend still independently checks owner and entitlements.

## Verification / production boundary

- `tests/test_studio_article_picker_105.cjs`: cross-resource typed selection, forbidden/missing/version mismatch, private-media preflight, Project snapshot/hydrate round-trip, bridge and script order; existing `test_studio_picker_interactions.cjs` and `test_studio_resources.cjs` cover other entry points and keyboard/busy/no-op.
- `tests/smoke_studio_picker_browser_105.py`: logged-in real Chromium, shared style/layout/ref picker, saved article Project CAS confirmation, reload, responsive viewport; local SQLite and owned media fixture, no paid image generation.
- Existing backend resource ownership and Project tests, complete 14-job Actions matrix, and the article/series/canvas smoke suite remain mandatory.
- Live supplier billing/cancellation, cross-device gallery rehydration, production PG/Redis/object store recovery and all-user/browser matrix are release acceptance obligations of Issue #112, not evidence of a paid production test.
