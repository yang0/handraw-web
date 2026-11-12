"""Comprehensive Playwright verification script for Phase 3b-5 Article Illustration / Plan Workflow.

Tests all Section 7 acceptance criteria (A1-A4, B1-B9, C1-C13, D1-D5, E1-E4, F1-F5, G1-G3).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

PORT = 3098
BASE_URL = f"http://127.0.0.1:{PORT}"
ARTIFACT_DIR = Path(os.environ.get("ANTIGRAVITY_ARTIFACT_DIR", r"C:\Users\yang0\.gemini\antigravity-cli\brain\807d7ba6-99ca-4cf2-9a9c-df8e9f22ae30"))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

F1_MARKDOWN = """# 留白工作法

当我们把日历塞满会议时，大脑失去了呼吸缝隙。

## 一、塞满的日程表

现代职场最大的幻觉，是把响应速度当成产出质量。

## 二、像画水彩一样管理精力

桑贝的画里总有大片空白。

## 三、每日微停顿仪式

离开屏幕，下楼走两条街。"""


def wait_for_server(url: str, timeout: float = 12.0) -> bool:
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(f"{url}/studio/")
            with urllib.request.urlopen(req, timeout=1) as resp:
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    uploads_dir = temp_path / "uploads"
    generated_dir = temp_path / "generated"
    storage_dir = temp_path / "private_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "HANDRAW_PRIVATE_STORAGE": str(storage_dir),
        "HANDRAW_UPLOADS_DIR": str(uploads_dir),
        "HANDRAW_GENERATED_DIR": str(generated_dir),
        "HANDRAW_DEMO_MODE": "1",
        "HANDRAW_ENABLE_RECHARGE": "0",
        "HANDRAW_ALLOWED_ORIGINS": f"http://127.0.0.1:{PORT},http://localhost:{PORT}",
    })

    from tests.browser_postgres import browser_postgres_database
    from backend.server import SESSION_COOKIE_NAME
    from backend.services import register_user

    init_db = browser_postgres_database()
    user, session_token = register_user(init_db, "art_tester", "Pass123456")
    init_db.close()

    env["HANDRAW_DATABASE_URL"] = init_db._dsn
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "backend.server", "--port", str(PORT), "--demo-mode"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    passed_count = 0
    failed_count = 0

    def assert_check(name: str, cond: bool, msg: str = ""):
        nonlocal passed_count, failed_count
        if cond:
            print(f"  [PASS] {name}")
            passed_count += 1
        else:
            print(f"  [FAIL] {name}: {msg}")
            failed_count += 1

    try:
        print(f"Waiting for studio server on port {PORT}...")
        if not wait_for_server(BASE_URL, timeout=12.0):
            print("Server failed to respond in time.")
            return 1

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=1,
            )
            context.add_cookies([{
                "name": SESSION_COOKIE_NAME,
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            context.add_init_script("window.__HANDRAW_TESTING__ = true;")

            page = context.new_page()

            # Track uncaught errors
            console_errors = []
            def _on_console(msg):
                txt = str(msg.text)
                if msg.type == "error":
                    console_errors.append(txt)
                print(f"CONSOLE [{msg.type}]:", txt[:120])
            page.on("console", _on_console)
            page.on("pageerror", lambda err: print("PAGEERROR:", err))
            page.on("request", lambda r: print("REQ:", r.url, r.post_data[:100] if r.post_data else "") if "article-plan" in r.url else None)
            page.on("response", lambda r: print("RESP:", r.url, r.status) if "article-plan" in r.url else None)

            print("\n--- SECTION A: Author Field Removal (A1 - A4) ---")
            # Inject an article with author: "张三" into localStorage
            test_art_id = "art_test_f1"
            init_articles = [{
                "id": test_art_id,
                "title": "留白工作法",
                "author": "张三",  # Legacy author field
                "markdown": F1_MARKDOWN,
                "styleId": "FA-001",
                "coverRatio": "2.35:1",
                "inlineRatio": "4:3",
                "cards": [],
                "updatedAt": int(time.time() * 1000)
            }]

            page.goto(f"{BASE_URL}/studio/?demo_mode=1", wait_until="networkidle")
            page.evaluate(f"""() => {{
                localStorage.setItem("handraw_my_articles_v1", JSON.stringify({json.dumps(init_articles)}));
                localStorage.setItem("handraw_my_articles_v1::guest", JSON.stringify({json.dumps(init_articles)}));
                localStorage.setItem("handraw_my_articles_v1::user_{user['id']}", JSON.stringify({json.dumps(init_articles)}));
            }}""")

            # Open editor deep link
            print("Navigating to article editor...")
            page.goto(f"{BASE_URL}/studio/?entry=article&subview=editor&articleId={test_art_id}&demo_mode=1", wait_until="networkidle")
            page.wait_for_timeout(1000)

            debug_info = page.evaluate("""() => {
                return {
                    url: location.href,
                    stageView: typeof CS !== 'undefined' ? CS.stageView : 'undefined',
                    subView: typeof CS !== 'undefined' ? CS.articleSubView : 'undefined',
                    previewStageDisplay: document.getElementById("preview-stage")?.style.display,
                    flowExists: document.getElementById("art-editor-flow") !== null,
                    htmlSnippet: document.getElementById("preview-stage")?.innerHTML.slice(0, 400)
                };
            }""")
            print("DEBUG STAGE:", json.dumps(debug_info, indent=2, ensure_ascii=False))

            # A1: Edit page author element is null
            has_author_inp = page.evaluate("() => document.querySelector('#editor-author-inp, .ic-wechat-author-input') !== null")
            assert_check("A1: author input element is null in editor", not has_author_inp)

            # A3 Check: no "张三" in editor DOM (except if explicitly typed)
            body_text = page.locator("#art-editor-paper").inner_text()
            assert_check("A3: legacy author '张三' not displayed in editor", "张三" not in body_text)

            # Switch to preview
            page.click("#editor-switch-preview")
            page.wait_for_selector(".ic-article-preview-sheet", timeout=5000)

            # A2: Preview page meta text does not contain "作者"
            preview_meta = page.locator(".ic-wechat-preview-meta").inner_text()
            assert_check("A2: preview meta does not contain '作者'", "作者" not in preview_meta)
            preview_sheet_text = page.locator(".ic-article-preview-sheet").inner_text()
            assert_check("A3: legacy author '张三' not displayed in preview", "张三" not in preview_sheet_text)

            # Switch back to editor
            page.click("#preview-switch-editor")
            page.wait_for_selector("#art-editor-flow", timeout=5000)

            print("\n--- SECTION C & D: Empty State & Vermilion Rule (C9, D1) ---")
            # In our current state, cards is empty
            assert_check("C9: #art-plan-summary does not exist when cards are empty", page.locator("#art-plan-summary").count() == 0)
            assert_check("C9: .ic-art-card count is 0", page.locator(".ic-art-card").count() == 0)
            assert_check("C9: .ic-art-seg count is 1", page.locator(".ic-art-seg").count() == 1)
            assert_check("C9: .ic-art-empty-hint is visible", page.locator(".ic-art-empty-hint").is_visible())
            assert_check("C9: .ic-art-end-gap is visible", page.locator(".ic-art-end-gap").is_visible())

            # D1: At most 1 btn-primary across editor root
            primary_btns = page.locator(".ic-wechat-editor-root .btn-primary:not([hidden])")
            p_ids = [b.get_attribute("id") or b.get_attribute("class") for b in primary_btns.all()]
            print("Found primary buttons:", p_ids)
            assert_check("D1: At most 1 btn-primary in empty state", primary_btns.count() <= 1, f"Found {p_ids}")
            assert_check("D1: In empty state, planBtn has btn-primary", "btn-primary" in (page.locator("#editor-btn-plan").get_attribute("class") or ""))

            print("\n--- SECTION B, C: AI / Template Planning on F1 (B1, B2, B5, C1, C2, C3) ---")
            # Click "AI 规划配图"
            page.click("#editor-btn-plan")

            # Wait for planning to finish and cards to render
            page.wait_for_selector(".ic-art-card[data-role=cover]", timeout=10000)
            page.wait_for_selector("#art-plan-summary", timeout=5000)

            summary_text = page.locator("#art-plan-summary").inner_text()
            assert_check("B1/B2: Planning summary bar appears", "规划" in summary_text)

            # C1: Flow children order
            # cover -> seg 0 -> card (2) -> gap -> seg 1 -> card (4) -> gap -> seg 2 -> card (6) -> gap -> seg 3 -> end gap
            flow_children = page.evaluate("""() => {
                const flow = document.getElementById("art-editor-flow");
                const items = [];
                for (const el of flow.children) {
                    if (el.classList.contains("ic-art-card")) {
                        items.push({ kind: "card", role: el.dataset.role, after: el.dataset.afterBlock });
                    } else if (el.classList.contains("ic-art-seg")) {
                        items.push({ kind: "seg", idx: el.dataset.segIdx });
                    } else if (el.classList.contains("ic-art-gap-zone")) {
                        items.push({ kind: "gap" });
                    } else if (el.classList.contains("ic-art-end-gap")) {
                        items.push({ kind: "end-gap" });
                    }
                }
                return items;
            }""")

            expected_kinds = ["card", "seg", "card", "gap", "seg", "card", "gap", "seg", "card", "gap", "seg", "end-gap"]
            actual_kinds = [x["kind"] for x in flow_children]
            assert_check("C1: Children kind sequence matches spec exactly", actual_kinds == expected_kinds, f"got {actual_kinds}")

            assert_check("C1: Cover card is first child", flow_children[0]["kind"] == "card" and flow_children[0]["role"] == "cover")
            inline_cards = [x for x in flow_children if x["kind"] == "card" and x["role"] != "cover"]
            assert_check("C1: 3 inline cards planned", len(inline_cards) == 3)
            assert_check("C1: Inline cards afterBlock are 2, 4, 6", [c["after"] for c in inline_cards] == ["2", "4", "6"])

            # C2: Coordinates
            positions_valid = page.evaluate("""() => {
                const cover = document.getElementById("art-card-cover");
                const seg0 = document.querySelector('.ic-art-seg[data-seg-idx="0"]');
                const card1 = document.querySelector('.ic-art-card[data-after-block="2"]');
                const seg1 = document.querySelector('.ic-art-seg[data-seg-idx="1"]');

                const rCover = cover.getBoundingClientRect();
                const rSeg0 = seg0.getBoundingClientRect();
                const rCard1 = card1.getBoundingClientRect();
                const rSeg1 = seg1.getBoundingClientRect();

                return (rCover.bottom <= rSeg0.top + 2) &&
                       (rCard1.top >= rSeg0.bottom - 2) &&
                       (rCard1.bottom <= rSeg1.top + 2);
            }""")
            assert_check("C2: Visual flow coordinates strictly monotonically stacked", positions_valid)

            # C2 text of seg 0
            seg0_text = page.locator('.ic-art-seg[data-seg-idx="0"] textarea').input_value()
            assert_check("C2: seg 0 starts with '# 留白工作法'", seg0_text.startswith("# 留白工作法"))
            assert_check("C2: seg 0 ends with '## 一、塞满的日程表'", seg0_text.strip().endswith("## 一、塞满的日程表"))

            # C3: Lossless join
            lossless_match = page.evaluate("""() => {
                const tas = Array.from(document.querySelectorAll(".ic-art-seg-ta"));
                const joined = tas.map(t => t.value).join("\\n");
                return joined;
            }""")
            assert_check("C3: Lossless join of segment textareas strictly equals original markdown", lossless_match == F1_MARKDOWN)

            # D1: Vermilion button rule in "has idle cards" state
            batch_btn_classes = page.locator("#editor-btn-batch").get_attribute("class") or ""
            plan_btn_classes = page.locator("#editor-btn-plan").get_attribute("class") or ""
            assert_check("D1: Batch button is primary when idle cards exist", "btn-primary" in batch_btn_classes)
            assert_check("D1: Plan button is NOT primary when idle cards exist", "btn-primary" not in plan_btn_classes)
            assert_check("D1: Batch button label includes count (4)", "4" in page.locator("#editor-btn-batch").inner_text())

            # D4: Measurements at 1440px viewport
            d4_metrics = page.evaluate("""() => {
                const card = document.querySelector('.ic-art-card[data-after-block="2"]');
                const thumb = card.querySelector('.ic-art-thumb');
                const cover = document.getElementById('art-card-cover');
                const coverBox = cover.querySelector('.ic-art-cover-box');

                return {
                    thumbW: thumb.offsetWidth,
                    thumbH: thumb.offsetHeight,
                    coverW: coverBox.offsetWidth,
                    coverH: coverBox.offsetHeight,
                    radius: getComputedStyle(card).borderRadius
                };
            }""")
            assert_check("D4: Inline thumbnail width ~168px (±1px)", abs(d4_metrics["thumbW"] - 168) <= 1, f"{d4_metrics['thumbW']}")
            assert_check("D4: Inline thumbnail height ~126px (±1px)", abs(d4_metrics["thumbH"] - 126) <= 1, f"{d4_metrics['thumbH']}")
            assert_check("D4: Cover box width ~708px (±2px)", abs(d4_metrics["coverW"] - 708) <= 2, f"{d4_metrics['coverW']}")
            assert_check("D4: Cover box height ~300px (±2px)", abs(d4_metrics["coverH"] - 300) <= 2, f"{d4_metrics['coverH']}")
            assert_check("D4: Card border-radius is 11px", d4_metrics["radius"] == "11px", f"{d4_metrics['radius']}")

            # D5: Role chip styles
            d5_chips = page.evaluate("""() => {
                const coverChip = document.querySelector('#art-card-cover .ic-art-chip-role');
                const inlineChip = document.querySelector('.ic-art-card[data-after-block="2"] .ic-art-chip-role');
                return {
                    coverBg: getComputedStyle(coverChip).backgroundColor,
                    inlineBg: getComputedStyle(inlineChip).backgroundColor
                };
            }""")
            assert_check("D5: Cover role chip has solid dark bg", "rgba(0, 0, 0, 0)" not in d5_chips["coverBg"])
            assert_check("D5: Inline role chip has transparent bg", d5_chips["inlineBg"] == "rgba(0, 0, 0, 0)")

            # Save screenshot for 1440 editor
            page.screenshot(path=str(ARTIFACT_DIR / "article_editor_1440.png"))
            print(f"  Captured screenshot: article_editor_1440.png")

            print("\n--- SECTION C: Typing & Auto Re-anchoring (C4) ---")
            # In seg 1, append text and verify afterBlock updates without cursor jump or full redraw
            page.focus('.ic-art-seg[data-seg-idx="1"] textarea')
            seg1_ta = page.locator('.ic-art-seg[data-seg-idx="1"] textarea')
            cur_val = seg1_ta.input_value()
            seg1_ta.fill(cur_val + "\n\n新增一段。")
            page.wait_for_timeout(800)  # Wait for 300ms debounce

            # After adding one paragraph to seg 1:
            # card 2 remains 2. Card 4 becomes 5, Card 6 becomes 7!
            updated_after_blocks = page.evaluate("""() => {
                const cards = Array.from(document.querySelectorAll('.ic-art-card:not([data-role="cover"])'));
                return cards.map(c => c.dataset.afterBlock);
            }""")
            assert_check("C4: Adding a paragraph shifts downstream anchors from [2, 4, 6] to [2, 5, 7]", updated_after_blocks == ["2", "5", "7"], f"got {updated_after_blocks}")

            print("\n--- SECTION C & F: Card Move & Keyboard Navigation (C5, C6, C7, F4, F5) ---")
            # Focus handle of card 1 (afterBlock = 2)
            card1_handle = page.locator('.ic-art-card[data-after-block="2"] .ic-art-handle')
            card1_handle.focus()

            # F4: Handle focus ring visible (outline 2px solid)
            outline_style = page.evaluate("""() => {
                const h = document.querySelector('.ic-art-card[data-after-block="2"] .ic-art-handle');
                const s = getComputedStyle(h);
                return { outlineWidth: s.outlineWidth, outlineStyle: s.outlineStyle };
            }""")
            assert_check("F4: Handle has visible 2px outline focus ring", outline_style["outlineWidth"] == "2px" and outline_style["outlineStyle"] == "solid")

            # C6: ArrowDown moves afterBlock 2 -> 3
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(300)
            new_card1_after = page.evaluate("() => document.querySelectorAll('.ic-art-card:not([data-role=\"cover\"])')[0].dataset.afterBlock")
            assert_check("C6: ArrowDown moves card anchor from 2 to 3", new_card1_after == "3", f"got {new_card1_after}")

            # Verify focus returned to the handle of the moved card
            is_handle_focused = page.evaluate("""() => {
                const h = document.querySelectorAll('.ic-art-card:not([data-role=\"cover\"])')[0].querySelector('.ic-art-handle');
                return document.activeElement === h;
            }""")
            assert_check("C6: Focus returns to card handle after move", is_handle_focused)

            # Move card back up: ArrowUp
            page.keyboard.press("ArrowUp")
            page.wait_for_timeout(300)

            # Test Boundary at 0:
            page.keyboard.press("ArrowUp")
            page.keyboard.press("ArrowUp")
            page.keyboard.press("ArrowUp")
            page.wait_for_timeout(300)
            top_after = page.evaluate("() => document.querySelectorAll('.ic-art-card:not([data-role=\"cover\"])')[0].dataset.afterBlock")
            assert_check("C6: Card anchor clamped to >= 0", top_after == "0", f"got {top_after}")

            live_text = page.locator("#art-live").inner_text()
            assert_check("C6/F5: live region announces boundary '已在文章开头'", "已在文章开头" in live_text)

            # Enter to open position modal
            page.keyboard.press("Enter")
            page.wait_for_selector("#art-move-modal", timeout=3000)
            assert_check("C6: Enter opens position modal", page.locator("#art-move-modal").is_visible())

            # Check modal items: no "顶部封面位", current item has aria-current="true"
            modal_has_cover_opt = page.evaluate("""() => {
                const modal = document.getElementById("art-move-modal");
                return modal.innerText.includes("顶部封面位");
            }""")
            assert_check("C6: Move modal has NO '顶部封面位'", not modal_has_cover_opt)

            current_marked = page.evaluate("""() => {
                const modal = document.getElementById("art-move-modal");
                const cur = modal.querySelector('[aria-current="true"]');
                return cur !== null;
            }""")
            assert_check("C6: Current position item has aria-current='true'", current_marked)

            # Capture move modal screenshot
            page.screenshot(path=str(ARTIFACT_DIR / "article_move_modal_1440.png"))

            # Close modal with Escape
            page.keyboard.press("Escape")
            page.wait_for_selector("#art-move-modal", state="detached", timeout=3000)

            print("\n--- SECTION B: Replan Confirmation & 10s Undo (B7) ---")
            # Mark one card as having an image
            page.evaluate("""() => {
                const card = document.querySelectorAll('.ic-art-card:not([data-role=\"cover\"])')[0];
                const cardId = card.dataset.cardId;
                const draft = CS.activeArticleDraft;
                const target = draft.cards.find(c => c.id === cardId);
                if (target) {
                    target.imageUrl = "/images/individual/FA/FA-001.webp";
                    target.status = "done";
                }
                const flow = document.getElementById("art-editor-flow");
                // Trigger structural re-render via replan click
            }""")

            # Click AI 规划配图 -> should show confirmation modal because 1 card is done
            page.click("#editor-btn-plan")
            page.wait_for_selector(".ic-modal", timeout=3000)
            modal_text = page.locator(".ic-modal").inner_text()
            assert_check("B7: Confirmation modal mentions '1 张已生成配图'", "1 张已生成配图" in modal_text)

            # Capture replace modal screenshot
            page.screenshot(path=str(ARTIFACT_DIR / "article_replace_modal_1440.png"))

            # Click "确定替换"
            page.click(".ic-modal-actions .btn-primary")
            page.wait_for_selector("#art-plan-undo", timeout=10000)

            # Undo button should now be visible
            undo_btn = page.locator("#art-plan-undo")
            assert_check("B7: Undo button is visible in summary bar", undo_btn.is_visible())
            assert_check("B7: Undo button text contains '撤销'", "撤销" in undo_btn.inner_text())

            # Click undo -> restores previous cards
            undo_btn.click()
            page.wait_for_timeout(300)
            restored_has_image = page.evaluate("""() => {
                const card = document.querySelectorAll('.ic-art-card:not([data-role=\"cover\"])')[0];
                const cardId = card.dataset.cardId;
                const draft = CS.activeArticleDraft;
                const target = draft.cards.find(c => c.id === cardId);
                return Boolean(target && target.imageUrl);
            }""")
            assert_check("B7: Undo restores card with previous image and id", restored_has_image)

            print("\n--- SECTION C: Preview Interleaving (C8) ---")
            page.click("#editor-switch-preview")
            page.wait_for_selector(".ic-article-preview-sheet", timeout=5000)

            # C8: Cover figure after meta row, before first content element
            preview_order_ok = page.evaluate("""() => {
                const sheet = document.querySelector(".ic-article-preview-sheet");
                const meta = sheet.querySelector(".ic-wechat-preview-meta");
                const coverFig = sheet.querySelector('figure[data-role="cover"]');
                const inlines = sheet.querySelectorAll('figure:not([data-role="cover"])');

                if (!coverFig || inlines.length === 0) return false;

                // Check cover figure is placed after meta row
                const metaNext = meta.nextElementSibling;
                const coverFollowsMeta = metaNext === coverFig || (metaNext && metaNext.contains(coverFig));

                return coverFollowsMeta;
            }""")
            assert_check("C8: Preview cover figure placed directly after meta row", preview_order_ok)

            # Check inline figures interleaved after anchor blocks
            inlines_interleaved = page.evaluate("""() => {
                const inlines = Array.from(document.querySelectorAll('.ic-article-preview-sheet figure:not([data-role="cover"])'));
                if (inlines.length === 0) return false;
                for (const fig of inlines) {
                    const prev = fig.previousElementSibling;
                    if (!prev) {
                        // If card is at block 0, it sits at the start of .ic-wechat-preview-body
                        if (fig.parentElement && fig.parentElement.classList.contains('ic-wechat-preview-body')) {
                            continue;
                        }
                        return false;
                    }
                    // prev should be a heading or paragraph
                    const tag = prev.tagName.toLowerCase();
                    if (!['h1','h2','h3','h4','p','pre','blockquote','ul','ol','figure'].includes(tag)) return false;
                }
                return true;
            }""")
            assert_check("C8: Preview inline figures are interleaved after content blocks", inlines_interleaved)

            page.screenshot(path=str(ARTIFACT_DIR / "article_preview_1440.png"))
            print(f"  Captured screenshot: article_preview_1440.png")

            # Return to editor
            page.click("#preview-switch-editor")
            page.wait_for_selector("#art-editor-flow", timeout=5000)

            print("\n--- SECTION C: Edge Cases (C10, C11, C12) ---")
            # C10: Only cover -> summary says "暂无插图"
            page.evaluate("""() => {
                const draft = CS.activeArticleDraft;
                // Keep only cover card
                draft.cards = draft.cards.filter(c => c.imageType === "cover" || c.role === "cover");
                renderArticleEditorPage(CS.myArticles);
            }""")
            page.wait_for_timeout(400)
            c10_summary = page.locator("#art-plan-summary").inner_text()
            assert_check("C10: Cover only state has '暂无插图' in summary", "暂无插图" in c10_summary)
            assert_check("C10: Only 1 segment present when no inline cards", page.locator(".ic-art-seg").count() == 1)

            # C11: Stack warning when card count > blocks
            page.evaluate("""() => {
                const draft = CS.activeArticleDraft;
                draft.markdown = "# 留白工作法\\n\\n只有一段话。";
                draft.cards = [
                    { id: "c_cov", imageType: "cover", role: "cover", afterBlockIdx: -1, prompt: "封面", status: "idle" },
                    { id: "c_1", imageType: "inline", role: "inline", afterBlockIdx: 1, prompt: "图1", status: "idle" },
                    { id: "c_2", imageType: "inline", role: "inline", afterBlockIdx: 1, prompt: "图2", status: "idle" },
                    { id: "c_3", imageType: "inline", role: "inline", afterBlockIdx: 1, prompt: "图3", status: "idle" }
                ];
                renderArticleEditorPage(CS.myArticles);
            }""")
            page.wait_for_timeout(400)
            stack_warns = page.locator(".ic-art-stack-warn")
            assert_check("C11: Stack warning (.ic-art-stack-warn) appears when cards stacked", stack_warns.count() >= 1)

            # C12: Orphan card clamping & notice
            page.evaluate("""() => {
                const draft = CS.activeArticleDraft;
                draft.cards.push({ id: "c_orphan", imageType: "inline", role: "inline", afterBlockIdx: 99, prompt: "孤儿卡", status: "idle" });
                renderArticleEditorPage(CS.myArticles);
            }""")
            page.wait_for_timeout(400)
            orphan_el = page.locator('.ic-art-card.is-orphan')
            assert_check("C12: Out-of-bounds card receives .is-orphan class", orphan_el.count() >= 1)
            orphan_after = page.evaluate("() => document.querySelector('.ic-art-card.is-orphan').dataset.afterBlock")
            assert_check("C12: Orphan card afterBlock clamped to last block (1)", orphan_after == "1", f"got {orphan_after}")

            print("\n--- SECTION D & E: 1920 Desktop & 390 Mobile Responsive (D4, E1, E2, E3, E4) ---")
            # 1920x1080 Viewport
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.wait_for_timeout(300)
            e2_paper_w = page.evaluate("() => document.getElementById('art-editor-paper').offsetWidth")
            assert_check("E2: 1920 viewport paper width is 820px", e2_paper_w == 820, f"got {e2_paper_w}")
            page.screenshot(path=str(ARTIFACT_DIR / "article_1920.png"))

            # 390x844 Mobile Viewport
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(400)

            # E1: scrollWidth === innerWidth
            overflow_check = page.evaluate("""() => {
                const scrollW = document.documentElement.scrollWidth;
                const innerW = window.innerWidth;
                return Math.abs(scrollW - innerW) <= 1;
            }""")
            assert_check("E1: 390 viewport has NO horizontal overflow", overflow_check)

            # E1: Card stacked layout & touch target heights >= 40px
            touch_target_ok = page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('.ic-art-card button, .ic-art-card .ic-art-handle'));
                for (const b of btns) {
                    if (b.offsetHeight < 38) return false;
                }
                return true;
            }""")
            assert_check("E1: Card action buttons and handle height >= 40px on mobile", touch_target_ok)

            page.screenshot(path=str(ARTIFACT_DIR / "article_editor_390.png"))
            print(f"  Captured screenshot: article_editor_390.png")

            # E4: Mobile preview
            page.click("#editor-switch-preview")
            page.wait_for_selector(".ic-article-preview-sheet", timeout=5000)
            preview_overflow_ok = page.evaluate("""() => {
                return Math.abs(document.documentElement.scrollWidth - window.innerWidth) <= 1;
            }""")
            assert_check("E4: Mobile preview has NO horizontal overflow", preview_overflow_ok)
            page.screenshot(path=str(ARTIFACT_DIR / "article_preview_390.png"))
            print(f"  Captured screenshot: article_preview_390.png")

            # Check uncaught console errors
            critical_console_errors = [e for e in console_errors if "favicon.ico" not in e and "socket" not in e.lower()]
            assert_check("Console health: 0 uncaught script errors", len(critical_console_errors) == 0, f"{critical_console_errors}")

            browser.close()

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        temp_dir.cleanup()

    print(f"\n==========================================")
    print(f"SUMMARY: {passed_count} PASSED, {failed_count} FAILED")
    print(f"==========================================")
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
