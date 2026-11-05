"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");

const studio = fs.readFileSync("demo/assets/studio-app.js", "utf8");

// 1. Uploaded article is parsed and directly saved into CS.myArticles (history list)
assert.match(studio, /CS\.myArticles\.unshift\(newArt\)/, "Uploaded articles must be unshifted into CS.myArticles");
assert.match(studio, /persistMyArticles\(\)/, "Must persist articles on upload");
assert.match(studio, /AI 解析成功，文章已直接存入历史文章列表！/, "Toast confirming direct addition to history list");

// 2. Editing overwrites previous state in history
assert.match(studio, /function syncArticleEditorDraftToHistory/, "Must define syncArticleEditorDraftToHistory helper");
assert.match(studio, /targetArt\.articleTitle = title/, "Must overwrite articleTitle in history");
assert.match(studio, /targetArt\.markdown = md/, "Must overwrite markdown in history");
assert.match(studio, /targetArt\.style1 = draft\.styleId/, "Must overwrite style1 in history");

// 3. Editor inputs and events trigger syncArticleEditorDraftToHistory
assert.match(studio, /triggerDebouncedSync\(\)/, "Must have debounced auto-sync on input");
assert.match(studio, /window\.addEventListener\("beforeunload",\s*handleBeforeUnload\)/, "Must save on window beforeunload via addEventListener");
assert.match(studio, /const handleBeforeUnload\s*=\s*\(\s*\)\s*=>/, "Must define handleBeforeUnload for beforeunload listener");
assert.match(studio, /createNewArticlePlan\({\s*articleId: draft\.id/, "Planning must link articleId to avoid duplicate records");

// 4. Refreshing with entry=article restores editor state through the unified editor
assert.match(studio, /function openUnifiedArticleEditor/, "Must define unified article editor entry");
assert.match(studio, /flushUnifiedArticleEditor\(\)/, "Opening editor must flush prior draft");
assert.match(studio, /CS\.articleEditorDraft = draft/, "Hydration path must restore articleEditorDraft from resolved article");
assert.match(studio, /draftFromArticle\(art\)/, "Hydration must derive draft from the resolved article");
assert.match(studio, /url\.searchParams\.set\("subview", "editor"\)/, "Editor URL must be normalized to subview=editor");
assert.match(studio, /syncArticleEditorDraftToHistory\(draft, \{ bumpTime: true \}\)/, "Planning must persist the current draft into history");

// 5. Paginated history page has direct edit button
assert.match(studio, /data-edit-art-btn/, "Paginated list must offer direct edit button");

console.log("Article history persistence & overwrite contracts passed!");
