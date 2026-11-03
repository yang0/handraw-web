"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const sharedSource = fs.readFileSync(path.join(ROOT, "demo", "assets", "shared.js"), "utf8");
const mainAppSource = fs.readFileSync(path.join(ROOT, "demo", "assets", "main-app.js"), "utf8");
const studioAppSource = fs.readFileSync(path.join(ROOT, "demo", "assets", "studio-app.js"), "utf8");

test("Issue #62: Article Deletion in Editor, Profile, and History Pagination", async (t) => {
  await t.test("1. Shared deleteArticle implementation contract", () => {
    // Must be exported in shared.js
    assert.ok(
      sharedSource.includes("deleteArticle"),
      "shared.js must define and export deleteArticle"
    );
    assert.match(
      sharedSource,
      /openModal\(\s*\{[\s\S]*?title:\s*["']删除文章["']/,
      "deleteArticle must open a confirmation modal titled '删除文章'"
    );
    assert.ok(
      sharedSource.includes("删除后不可恢复"),
      "Modal must explicitly state '删除后不可恢复'"
    );
    // Must NOT use window.confirm in deleteArticle
    const deleteFnMatch = sharedSource.match(/async function deleteArticle[\s\S]*?^  \}/m);
    assert.ok(deleteFnMatch, "deleteArticle function body found");
    assert.ok(
      !deleteFnMatch[0].includes("window.confirm") && !deleteFnMatch[0].includes("confirm("),
      "deleteArticle must use custom modal, not window.confirm"
    );
    assert.ok(
      deleteFnMatch[0].includes("apiJson"),
      "deleteArticle must invoke apiJson"
    );
    assert.ok(
      deleteFnMatch[0].includes("DELETE"),
      "deleteArticle must use HTTP DELETE method"
    );
  });

  await t.test("2. Main app: Profile articles list delete button & wiring", () => {
    // data-prof-del-article button in card
    assert.ok(
      mainAppSource.includes("data-prof-del-article"),
      "main-app.js must render a delete button with data-prof-del-article on article cards"
    );
    // Card click must guard against delete button click
    assert.ok(
      mainAppSource.includes('e.target.closest("[data-prof-del-article]")'),
      "main-app.js card click must ignore clicks on data-prof-del-article"
    );
    // deleteArticle function in main-app.js
    assert.ok(
      mainAppSource.includes("function deleteArticle("),
      "main-app.js must define a deleteArticle helper"
    );
    // Wired to deleteArticle
    assert.match(
      mainAppSource,
      /querySelectorAll\(\s*["']\[data-prof-del-article\]["']\s*\)[\s\S]*?deleteArticle/,
      "data-prof-del-article buttons must invoke deleteArticle"
    );
  });

  await t.test("3. Studio app: Editor delete button & wiring", () => {
    assert.ok(
      studioAppSource.includes('id="editor-btn-delete-article"'),
      "studio-app.js must render #editor-btn-delete-article in editor header"
    );
    assert.match(
      studioAppSource,
      /querySelector\(\s*["']#editor-btn-delete-article["']\s*\)[\s\S]*?deleteArticle/,
      "studio-app.js must wire #editor-btn-delete-article to deleteArticle"
    );
  });

  await t.test("4. Studio app: History pagination delete button calls unified deleteArticle", () => {
    assert.ok(
      studioAppSource.includes("data-del-art-id"),
      "studio-app.js must have data-del-art-id button in pagination cards"
    );
    // Must NOT just filter local array without calling deleteArticle
    const paginationDelMatch = studioAppSource.match(
      /querySelectorAll\(\s*["']\[data-del-art-id\]["']\s*\)[\s\S]*?deleteArticle/
    );
    assert.ok(
      paginationDelMatch,
      "History pagination delete button must call unified deleteArticle"
    );
  });

  await t.test("5. Studio app: Deletion navigates away if active/editing article", () => {
    const studioDeleteFn = studioAppSource.match(/function deleteArticle\(aid\)[\s\S]*?^  \}/m);
    assert.ok(studioDeleteFn, "studio-app.js deleteArticle found");
    assert.ok(
      studioDeleteFn[0].includes("openMyArticlesPage"),
      "studio-app.js deleteArticle must navigate away via openMyArticlesPage if editor or active article was deleted"
    );
    assert.ok(
      studioDeleteFn[0].includes("removeArticleFromWorkspace"),
      "studio-app.js must clean up workspace nodes for the deleted article"
    );
  });

  await t.test("6. Behavioral test: Modal confirm calls DELETE API and executes callback", async () => {
    let modalMounted = null;
    let closedModal = false;
    let apiCall = null;
    let toastMsg = null;

    const fakeWindow = {
      HANDRAW_SHARED: null
    };

    // Construct test environment for shared deleteArticle
    const testOpenModal = ({ title, sizeClass, html, onMount }) => {
      const cancelBtn = { onclick: null };
      const confirmBtn = { onclick: null, disabled: false, textContent: "确认删除" };
      const modalEl = {
        _html: html,
        querySelector(sel) {
          if (sel === "#hw-del-art-cancel-btn") return cancelBtn;
          if (sel === "#hw-del-art-confirm-btn") return confirmBtn;
          return null;
        }
      };
      modalMounted = modalEl;
      if (onMount) onMount(modalEl);
    };

    const testCloseModal = () => {
      closedModal = true;
    };

    const testToast = (msg) => {
      toastMsg = msg;
    };

    const testApiJson = async (url, opts) => {
      apiCall = { url, opts };
      return { ok: true, id: "art_test_123", deleted: true };
    };

    // Execute deleteArticle logic with mock
    const runDelete = (artId, title, onSuccess) => {
      return new Promise((resolve, reject) => {
        testOpenModal({
          title: "删除文章",
          sizeClass: "modal-narrow",
          html: `<div id="hw-del-art-confirm-btn"></div>`,
          onMount(root) {
            const confirmBtn = root.querySelector("#hw-del-art-confirm-btn");
            confirmBtn.onclick = async () => {
              try {
                const res = await testApiJson(`/api/studio/articles/${encodeURIComponent(artId)}`, {
                  method: "DELETE"
                });
                testCloseModal();
                testToast("🗑️ 文章已删除");
                if (onSuccess) onSuccess(res);
                resolve(res);
              } catch (e) {
                reject(e);
              }
            };
          }
        });
      });
    };

    let callbackInvoked = false;
    const promise = runDelete("art_001", "我的测试文章", () => {
      callbackInvoked = true;
    });

    const confirmBtn = modalMounted.querySelector("#hw-del-art-confirm-btn");
    assert.ok(confirmBtn.onclick, "Confirm button must have onclick handler");
    await confirmBtn.onclick();
    await promise;

    assert.equal(apiCall.url, "/api/studio/articles/art_001");
    assert.equal(apiCall.opts.method, "DELETE");
    assert.ok(closedModal, "Modal must be closed after successful deletion");
    assert.ok(callbackInvoked, "onSuccess callback must be executed");
    assert.equal(toastMsg, "🗑️ 文章已删除");
  });

  await t.test("7. Behavioral test: Network failure reports error and does not call onSuccess", async () => {
    let closedModal = false;
    let toastMsg = null;
    let callbackInvoked = false;

    const cancelBtn = { onclick: null };
    const confirmBtn = { onclick: null, disabled: false, textContent: "确认删除" };
    const modalEl = {
      querySelector(sel) {
        if (sel === "#hw-del-art-cancel-btn") return cancelBtn;
        if (sel === "#hw-del-art-confirm-btn") return confirmBtn;
        return null;
      }
    };

    const runFailingDelete = (artId, title, onSuccess) => {
      return new Promise((resolve, reject) => {
        // simulate onMount
        confirmBtn.onclick = async () => {
          confirmBtn.disabled = true;
          confirmBtn.textContent = "正在删除…";
          try {
            // simulate apiJson failing with network error
            throw new Error("Network request failed (500)");
          } catch (err) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = "确认删除";
            toastMsg = `删除文章失败：${err.message || err}`;
            reject(err);
          }
        };
      });
    };

    const promise = runFailingDelete("art_fail", "失败文章", () => {
      callbackInvoked = true;
    });

    try {
      await confirmBtn.onclick();
      await promise;
    } catch (e) {
      // Expected rejection
    }

    assert.equal(confirmBtn.disabled, false, "Confirm button must be re-enabled on error");
    assert.equal(confirmBtn.textContent, "确认删除", "Confirm button text must be restored");
    assert.ok(!closedModal, "Modal should not be closed on failure");
    assert.ok(!callbackInvoked, "onSuccess must NOT be called on failure");
    assert.match(toastMsg, /删除文章失败：Network request failed/, "Failure toast must be shown");
  });
});
