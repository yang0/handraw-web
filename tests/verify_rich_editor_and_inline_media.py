import os
import sys
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\yang0\.gemini\antigravity\brain\0232e622-c0da-4d70-93ee-00d7c97adcae"
BASE_URL = "http://127.0.0.1:3080"

def run_verification():
    print(">>> Starting Playwright verification for Rich Text Editor & Inline Media/Cards...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Step 0: Log in as yang0
        print(">>> 0. Logging in via auth page...")
        page.goto(f"{BASE_URL}/forum.html?view=auth")
        page.wait_for_selector("#login-confirm-btn", timeout=6000)
        page.click("#login-confirm-btn")
        page.wait_for_timeout(600)

        # Step 1: Open Compose View
        print(">>> 1. Navigating to forum compose view...")
        page.goto(f"{BASE_URL}/forum.html?view=compose")
        page.wait_for_selector("#forum-compose-page", timeout=8000)

        # Check clean layout
        assert page.locator("#compose-title-input").is_visible(), "Title input missing"
        assert page.locator("#compose-editor-toolbar").is_visible(), "Editor toolbar missing"
        assert page.locator("#compose-rich-editor").is_visible(), "Rich contenteditable editor missing"
        assert page.locator("#compose-mode-dropdown").is_visible(), "Mode dropdown missing"
        assert page.locator("#compose-board-pills").is_visible(), "Board pills missing"

        # Verify old 6 fragmented numbered boxes are gone
        text_content = page.locator("#forum-compose-page").inner_text()
        assert "1. 选择目标论坛板块" not in text_content, "Old box 1 still present"
        assert "4. 🖼️ 附加图文配图" not in text_content, "Old box 4 still present"
        assert "5. 📎 附加分享卡片" not in text_content, "Old box 5 still present"
        print("  ✓ Old fragmented 6-box layout is successfully eliminated.")

        # Step 2: Fill Title
        print(">>> 2. Typing title into rich composer...")
        page.fill("#compose-title-input", "实测秋日水墨图文与排版全流程调优记录")

        # Step 3: Type paragraph 1 into rich editor
        print(">>> 3. Typing paragraph 1 into rich editor...")
        editor = page.locator("#compose-rich-editor")
        editor.click()
        page.keyboard.type("这是今天在 Handraw 社区实测的一套完整水墨风格方案。首先在画风库中精选了这一套表现极佳的画风：")
        page.keyboard.press("Enter")

        # Step 4: Insert a Style Card inline
        print(">>> 4. Inserting Style Card inline...")
        page.click("#tb-insert-style")
        page.wait_for_selector(".hw-modal-panel", timeout=5000)
        # Click the first card in picker
        page.locator(".hw-modal-panel [data-pick-card-id]").first.click()
        page.wait_for_timeout(400)

        # Verify card is inserted inline inside rich editor
        assert editor.locator(".hw-intext-card").count() >= 1, "Style card was not inserted into editor"
        print("  ✓ Style card inserted inline into editor successfully.")

        # Step 5: Type paragraph 2
        print(">>> 5. Typing paragraph 2...")
        editor.click()
        page.keyboard.press("PageDown")
        page.keyboard.type("接下来对比看一下在无限画布中渲染出的高清实测样片效果：")
        page.keyboard.press("Enter")

        # Step 6: Insert an Image inline (direct file chooser, no modal)
        print(">>> 6. Inserting an image inline...")
        temp_img = os.path.join(ARTIFACT_DIR, "scratch", "test_upload.png")
        if not os.path.exists(temp_img):
            import base64
            os.makedirs(os.path.dirname(temp_img), exist_ok=True)
            with open(temp_img, "wb") as f:
                f.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
        with page.expect_file_chooser() as fc_info:
            page.click("#tb-insert-image")
        fc_info.value.set_files(temp_img)
        page.wait_for_timeout(400)

        assert editor.locator(".hw-intext-media").count() >= 1, "Image was not inserted into editor"
        print("  ✓ Image figure inserted inline into editor successfully.")

        # Step 7: Type paragraph 3 and insert a Work Card inline
        print(">>> 7. Inserting a Work Card inline...")
        editor.click()
        page.keyboard.press("PageDown")
        page.keyboard.type("最后附带本次创作的终稿实测作品卡片，欢迎大家复刻交流：")
        page.keyboard.press("Enter")

        page.click("#tb-insert-work")
        page.wait_for_selector(".hw-modal-panel", timeout=5000)
        page.locator(".hw-modal-panel [data-pick-card-id]").first.click()
        page.wait_for_timeout(400)

        assert editor.locator(".hw-intext-card").count() >= 2, "Work card was not inserted into editor"
        print("  ✓ Work card inserted inline into editor successfully.")

        # Capture Compose Page Screenshot
        compose_shot = os.path.join(ARTIFACT_DIR, "v6_forum_rich_composer_inline_media.png")
        page.screenshot(path=compose_shot, full_page=True)
        print(f"  ✓ Saved composer screenshot: {compose_shot}")

        # Step 8: Submit Post
        print(">>> 8. Submitting post...")
        page.click("#compose-submit-btn")
        page.wait_for_selector("#standalone-topic-detail-page", timeout=8000)
        print("  ✓ Navigated to topic detail page successfully!")

        # Step 9: Verify Topic Detail Page Layout
        print(">>> 9. Verifying topic detail page layout...")
        # Check that disconnected 58vh giant gallery stage is gone
        assert page.locator(".hw-detail-stage").count() == 0, "Detached giant gallery stage still exists"
        assert page.locator(".forum-article-body").is_visible(), "Unified article body missing"

        # Check inline elements inside article body
        article_body = page.locator(".forum-article-body")
        assert article_body.locator(".smart-embed-card").count() >= 1, "Inline smart cards missing in article body"
        assert article_body.locator("img").count() >= 1, "Inline images missing in article body"
        print("  ✓ Images and cards are rendered seamlessly INLINE in the narrative flow!")

        # Step 10: Test Image Lightbox
        print(">>> 10. Testing image lightbox on click...")
        article_body.locator("img[data-zoom-img]").first.click()
        page.wait_for_selector(".hw-modal-panel", timeout=4000)
        assert page.locator(".hw-modal-panel img").is_visible(), "Lightbox modal did not display image"
        print("  ✓ Lightbox modal opened with high-resolution image.")
        # Close modal
        page.click("#hw-modal-close-x")
        page.wait_for_timeout(300)

        # Capture Detail Page Screenshot
        detail_shot = os.path.join(ARTIFACT_DIR, "v6_forum_topic_detail_inline_editorial.png")
        page.screenshot(path=detail_shot, full_page=True)
        print(f"  ✓ Saved detail screenshot: {detail_shot}")

        # Step 11: Return to Forum List and verify clean card snippet
        print(">>> 11. Navigating back to forum list...")
        page.click("#topic-back-list-btn")
        page.wait_for_selector(".forum-topic-card", timeout=6000)

        first_card = page.locator(".forum-topic-card").first
        first_card_text = first_card.inner_text()
        assert "<figure" not in first_card_text, "Raw HTML tag leaked into card snippet"
        assert "<div" not in first_card_text, "Raw HTML tag leaked into card snippet"
        print("  ✓ Forum list card renders clean text snippet without raw HTML tags.")

        list_shot = os.path.join(ARTIFACT_DIR, "v6_forum_list_clean_snippet.png")
        page.screenshot(path=list_shot, full_page=True)
        print(f"  ✓ Saved forum list screenshot: {list_shot}")

        browser.close()
        print(">>> ALL VERIFICATION CHECKS PASSED!")

if __name__ == "__main__":
    run_verification()
