"use strict";

// Issue #134: "AI 规划套图" threw ReferenceError because the Studio2 planning
// and undo handlers inside bindEvents() referenced `p` while only `parts` was
// destructured. This is a cheap static guard; the real browser flow is still
// required (see the issue's acceptance criteria).

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
  path.join(__dirname, "..", "demo", "assets", "studio-batch.js"), "utf8"
);

function bindEventsBody() {
  const start = source.indexOf("bindEvents(root, parts, iterations)");
  assert.ok(start > -1, "bindEvents definition must exist");
  // Brace matching from the opening brace of the method body.
  let i = source.indexOf("{", start);
  const open = i;
  let depth = 0;
  for (; i < source.length; i++) {
    const ch = source[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return source.slice(open, i + 1);
    }
  }
  throw new Error("unbalanced bindEvents body");
}

const body = bindEventsBody();

// 1. `p` must be bound inside bindEvents before any use.
assert.match(
  body,
  /(?:const|let|var)\s+p\s*=\s*parts\s*;/,
  "bindEvents must alias parts to p for the Studio2 AI handlers"
);

// 2. Every bare `p.<field>` reference must come after the alias declaration.
const aliasAt = body.search(/(?:const|let|var)\s+p\s*=\s*parts\s*;/);
const uses = [...body.matchAll(/(?<![A-Za-z0-9_$.])p\.(?:skill|text|ctrl)\b/g)]
  .map((m) => m.index);
assert.ok(uses.length > 0, "expected the Studio2 AI handlers to use p.*");
for (const index of uses) {
  assert.ok(
    index > aliasAt,
    `bare p.* use at offset ${index} precedes the p = parts alias`
  );
}

// 3. The planning call must pass the very same parts object that was bound.
assert.match(
  body,
  /parts\s*:\s*p\b/,
  "AI.apply / AI.undo must pass parts: p"
);

// 4. Keep the module parseable.
new (require("node:vm").Script)(source, { filename: "studio-batch.js" });

console.log("test_studio_batch_ai_plan_p_alias: ok");
