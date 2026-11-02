"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Load shared.js in isolated sandbox
function createSharedContext(hasDOMParser = true) {
  let docElements = [];

  class MockElement {
    constructor(tag) {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this._attrs = {};
      this.parent = null;
    }
    get textContent() {
      let t = "";
      for (const c of this.children) {
        if (typeof c === "string") t += c;
        else if (c && c.textContent) t += c.textContent;
      }
      return t;
    }
    set textContent(val) {
      this.children = [String(val)];
    }
    remove() {
      if (this.parent) {
        const idx = this.parent.children.indexOf(this);
        if (idx !== -1) this.parent.children.splice(idx, 1);
        this.parent = null;
      }
    }
    querySelectorAll(selector) {
      const matchTags = selector.toLowerCase().split(",").map((s) => s.trim().replace(/^\./, ""));
      const found = [];
      const walk = (el) => {
        for (const child of el.children) {
          if (typeof child !== "string") {
            const tagMatch = matchTags.includes(child.tagName.toLowerCase());
            const classMatch = child._attrs["class"] && matchTags.some((cls) => child._attrs["class"].includes(cls));
            if (tagMatch || classMatch) found.push(child);
            walk(child);
          }
        }
      };
      walk(this);
      return found;
    }
  }

  const context = vm.createContext({
    window: {},
    document: {
      createElement(tag) {
        return new MockElement(tag);
      },
      getElementById() {
        return null;
      },
      body: new MockElement("body")
    },
    DOMParser: hasDOMParser
      ? class MockDOMParser {
          parseFromString(html, type) {
            const doc = {
              body: new MockElement("body"),
              querySelectorAll(sel) {
                return this.body.querySelectorAll(sel);
              }
            };

            // Parse tags simply to simulate browser DOMParser behavior:
            // 1. Tag tokens
            const re = /<\s*(\/)?([a-zA-Z0-9-]+)([^>]*)>|([^<]+)/g;
            let m;
            let current = doc.body;
            const dropTags = new Set(["SCRIPT", "STYLE", "SVG", "MATH", "IFRAME", "OBJECT", "EMBED"]);

            while ((m = re.exec(html)) !== null) {
              const [full, isClose, tagName, attrStr, text] = m;
              if (text) {
                current.children.push(text);
                continue;
              }
              const tag = (tagName || "").toUpperCase();
              if (isClose) {
                if (current.parent && current.tagName === tag) {
                  current = current.parent;
                }
              } else {
                const el = new MockElement(tag);
                el.parent = current;
                // Parse class attr
                const classM = /class=["']([^"']*)["']/.exec(attrStr);
                if (classM) el._attrs["class"] = classM[1];
                current.children.push(el);
                if (!["BR", "IMG", "HR", "INPUT"].includes(tag)) {
                  current = el;
                }
              }
            }

            return doc;
          }
        }
      : undefined,
    console: { log() {}, warn() {}, error() {} },
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    URLSearchParams,
    URL
  });

  const sharedJs = fs.readFileSync(path.join(__dirname, "../demo/assets/shared.js"), "utf8");
  vm.runInContext(sharedJs, context);
  return context.window.HANDRAW_SHARED;
}

test("Text Injection Guard (Issue #54)", async (t) => {
  const S = createSharedContext(true);

  await t.test("Requirement 1: HTML entity escaping (esc)", () => {
    assert.equal(S.esc('<script>alert("xss")</script>'), "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;");
    assert.equal(S.esc("<img src='x' onerror='alert(1)'>"), "&lt;img src=&#39;x&#39; onerror=&#39;alert(1)&#39;&gt;");
    assert.equal(S.esc("1 < 2 & 3 > 2"), "1 &lt; 2 &amp; 3 &gt; 2");
    assert.equal(S.esc(null), "");
    assert.equal(S.esc(undefined), "");
  });

  await t.test("Requirement 2: safeHref protocol and character filtering", () => {
    // Dangerous protocols rejected
    assert.equal(S.safeHref("javascript:alert(1)"), "");
    assert.equal(S.safeHref("  javascript:alert(1)  "), "");
    assert.equal(S.safeHref("JAVASCRIPT:alert(1)"), "");
    assert.equal(S.safeHref("data:text/html,<script>alert(1)</script>"), "");
    assert.equal(S.safeHref("vbscript:msgbox(1)"), "");
    assert.equal(S.safeHref("file:///etc/passwd"), "");

    // Protocol-relative and backslash injections rejected
    assert.equal(S.safeHref("//evil.com/xss"), "");
    assert.equal(S.safeHref("/\\evil.com"), "");
    assert.equal(S.safeHref("\\\\evil.com"), "");

    // Control characters rejected
    assert.equal(S.safeHref("jav\x00ascript:alert(1)"), "");
    assert.equal(S.safeHref("/t/123\x1fbad"), "");

    // Safe absolute & relative URLs allowed
    assert.equal(S.safeHref("https://example.com/topic/1"), "https://example.com/topic/1");
    assert.equal(S.safeHref("http://127.0.0.1:3080/forum/"), "http://127.0.0.1:3080/forum/");
    assert.equal(S.safeHref("/t/topic_123?ref=test"), "/t/topic_123?ref=test");
    assert.equal(S.safeHref("/forum/?view=topics"), "/forum/?view=topics");
    assert.equal(S.safeHref("#replies"), "#replies");
    assert.equal(S.safeHref("mailto:artist@handraw-style.com"), "mailto:artist@handraw-style.com");

    // Falsy inputs
    assert.equal(S.safeHref(null), "");
    assert.equal(S.safeHref(""), "");
  });

  await t.test("Requirement 3: safeMediaUrl validation", () => {
    // Malicious media URLs rejected
    assert.equal(S.safeMediaUrl("javascript:alert(1)"), "");
    assert.equal(S.safeMediaUrl("data:text/html,<script>"), "");
    assert.equal(S.safeMediaUrl("data:image/svg+xml,<svg onload=alert(1)>"), "");
    assert.equal(S.safeMediaUrl("//evil.com/pic.png"), "");
    assert.equal(S.safeMediaUrl("/\\evil.com/pic.png"), "");

    // Safe media URLs allowed
    assert.equal(S.safeMediaUrl("/uploads/hero.png"), "/uploads/hero.png");
    assert.equal(S.safeMediaUrl("/demo/assets/hero.png"), "/demo/assets/hero.png");
    assert.equal(S.safeMediaUrl("/assets/theme.css"), "/assets/theme.css");
    assert.equal(S.safeMediaUrl("https://handraw-style.com/fa.webp"), "https://handraw-style.com/fa.webp");
    assert.equal(S.safeMediaUrl("http://example.com/cover.jpg"), "http://example.com/cover.jpg");

    // Valid Base64 image data URL with allowData: true
    const png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
    assert.equal(S.safeMediaUrl(png, { allowData: false }), "");
    assert.equal(S.safeMediaUrl(png, { allowData: true }), png);
  });

  await t.test("Requirement 4: stripHtmlToSnippet extracts safe plain text without leaks", () => {
    // 1. Script tag completely removed (not leaked as text)
    const scriptSnippet = S.stripHtmlToSnippet("<p>分享心得<script>alert(1)</script>收尾</p>");
    assert.equal(scriptSnippet, "分享心得收尾");

    // 2. Img tag removed
    const imgSnippet = S.stripHtmlToSnippet("精彩作品！<img src=x onerror=alert(1)>值得收藏！");
    assert.equal(imgSnippet, "精彩作品！值得收藏！");

    // 3. Anchor stripped, text kept
    const linkSnippet = S.stripHtmlToSnippet('<a href="javascript:alert(1)">点我查看</a>');
    assert.equal(linkSnippet, "点我查看");

    // 4. In-text delete buttons and badges removed
    const badgeSnippet = S.stripHtmlToSnippet('<div class="hw-honor-badge">徽章</div><p>段落内容</p><button class="btn">按钮</button>');
    assert.equal(badgeSnippet, "段落内容");

    // 5. Length bounding with ellipsis
    const longHtml = "<p>" + "作品内容".repeat(50) + "</p>";
    const bounded = S.stripHtmlToSnippet(longHtml, 20);
    assert.ok(bounded.endsWith("…"));
    assert.equal(bounded.length, 21); // 20 chars + '…'
  });

  await t.test("Requirement 5: Fallback path when DOMParser is unavailable", () => {
    const SNoDom = createSharedContext(false);
    assert.equal(SNoDom.stripHtmlToSnippet("<script>alert(1)</script>纯文本"), "纯文本");
    assert.equal(SNoDom.stripHtmlToSnippet("<img src=x onerror=alert(1)>好图"), "好图");
    assert.equal(SNoDom.stripHtmlToSnippet("未闭合标签<img src=x"), "未闭合标签");
    assert.equal(SNoDom.stripHtmlToSnippet("1 < 2 且 3 > 2"), "1 < 2 且 3 > 2");
  });

  await t.test("Requirement 6: Forum App integration and delegation", () => {
    const forumJs = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-app.js"), "utf8");
    assert.ok(
      forumJs.includes("if (S.stripHtmlToSnippet) return S.stripHtmlToSnippet(html, maxLen);"),
      "forum-app.js must delegate stripHtmlToSnippet to S.stripHtmlToSnippet"
    );

    const resourcesJs = fs.readFileSync(path.join(__dirname, "../demo/assets/forum-resources.js"), "utf8");
    assert.ok(
      resourcesJs.includes("if (S.stripHtmlToSnippet) return S.stripHtmlToSnippet(v, 99999);"),
      "forum-resources.js must delegate to S.stripHtmlToSnippet"
    );
  });
});
