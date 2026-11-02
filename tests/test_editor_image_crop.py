import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestEditorImageCrop(unittest.TestCase):
    def setUp(self):
        self.theme_css = (ROOT / "demo" / "assets" / "theme.css").read_text(encoding="utf-8")
        self.studio_app = (ROOT / "demo" / "assets" / "studio-app.js").read_text(encoding="utf-8")
        self.forum_app = (ROOT / "demo" / "assets" / "forum-app.js").read_text(encoding="utf-8")
        self.studio_canvas = (ROOT / "demo" / "assets" / "studio-canvas.css").read_text(encoding="utf-8")

    def test_01_card_selection_preview_contain_and_ratio(self):
        """Card selection preview must use fixed frame with object-fit: contain and no cover."""
        # theme.css defines .hw-picker-card-media with 1:1 and contain
        self.assertRegex(
            self.theme_css,
            r"\.hw-picker-card-media\s*\{[^}]*aspect-ratio:\s*1\s*/\s*1",
            ".hw-picker-card-media must have aspect-ratio: 1 / 1"
        )
        self.assertRegex(
            self.theme_css,
            r"\.hw-picker-card-media\s+img\s*\{[^}]*object-fit:\s*contain",
            ".hw-picker-card-media img must have object-fit: contain"
        )

        # studio-app.js batch gallery picker cards must use .hw-picker-card-media without inline cover
        self.assertIn("data-bgal-idx", self.studio_app)
        bgal_match = re.search(r'data-bgal-idx[\s\S]*?</div>\s*</div>', self.studio_app)
        self.assertIsNotNone(bgal_match, "data-bgal-idx block found")
        bgal_block = bgal_match.group(0)
        self.assertIn("hw-picker-card-media", bgal_block, "Gallery picker must use .hw-picker-card-media")
        self.assertNotIn("object-fit:cover", bgal_block.replace(" ", ""), "Must not have inline object-fit: cover")
        self.assertNotIn("aspect-ratio:3/4", bgal_block.replace(" ", ""), "Must not have inline aspect-ratio: 3/4")

    def test_02_rich_editor_body_images_natural_ratio(self):
        """Rich editor body images must adapt to native aspect ratio with width: auto; max-width: 100%; height: auto."""
        # theme.css shared rules for editor body images
        self.assertRegex(
            self.theme_css,
            r"\.hw-editor-body-img[^{]*\{[^}]*width:\s*auto",
            ".hw-editor-body-img must have width: auto"
        )
        self.assertRegex(
            self.theme_css,
            r"\.hw-editor-body-img[^{]*\{[^}]*max-width:\s*100%",
            ".hw-editor-body-img must have max-width: 100%"
        )
        self.assertRegex(
            self.theme_css,
            r"\.hw-editor-body-img[^{]*\{[^}]*height:\s*auto",
            ".hw-editor-body-img must have height: auto"
        )
        self.assertRegex(
            self.theme_css,
            r"\.hw-editor-body-img[^{]*\{[^}]*object-fit:\s*contain",
            ".hw-editor-body-img must have object-fit: contain"
        )

        # .hw-intext-media-wrap img must have width: auto, max-width: 100%, height: auto
        self.assertRegex(
            self.theme_css,
            r"\.hw-intext-media-wrap\s+img\s*\{[^}]*width:\s*auto",
            ".hw-intext-media-wrap img must have width: auto"
        )
        self.assertRegex(
            self.theme_css,
            r"\.hw-intext-media-wrap\s+img\s*\{[^}]*height:\s*auto",
            ".hw-intext-media-wrap img must have height: auto"
        )
        self.assertNotRegex(
            self.theme_css,
            r"\.hw-intext-media-wrap\s+img\s*\{[^}]*max-height:\s*520px",
            ".hw-intext-media-wrap img must not constrain max-height to 520px"
        )

        # forum-app.js buildIntextMediaHtml uses .hw-editor-body-img and onerror handler
        self.assertIn("hw-editor-body-img", self.forum_app)
        self.assertIn("hw-img-broken", self.forum_app)

        # studio-app.js renderPreviewFigureHtml uses .hw-editor-body-img without inline width:100%
        preview_figure_match = re.search(r'function renderPreviewFigureHtml[\s\S]*?return `\s*<figure class="ic-wechat-figure"[\s\S]*?</figure>', self.studio_app)
        self.assertIsNotNone(preview_figure_match)
        preview_block = preview_figure_match.group(0)
        self.assertIn("hw-editor-body-img", preview_block)
        self.assertNotIn('style="width:100%;border-radius:6px;display:block;"', preview_block)

    def test_03_modal_lightbox_large_image(self):
        """Modal large image preview must restrict max-height with contain, support scroll, and retain view original."""
        # theme.css defines .hw-modal-lightbox-container and .hw-modal-lightbox-img
        self.assertRegex(
            self.theme_css,
            r"\.hw-modal-lightbox-container\s*\{[^}]*overflow-y:\s*auto",
            ".hw-modal-lightbox-container must support scrolling"
        )
        self.assertRegex(
            self.theme_css,
            r"\.hw-modal-lightbox-img\s*\{[^}]*max-height:\s*72vh",
            ".hw-modal-lightbox-img must restrict max-height"
        )
        self.assertRegex(
            self.theme_css,
            r"\.hw-modal-lightbox-img\s*\{[^}]*object-fit:\s*contain",
            ".hw-modal-lightbox-img must use object-fit: contain"
        )

        # studio-app.js openImageLightbox uses shared lightbox classes and provides view original link
        lb_studio_match = re.search(r'function openImageLightbox\(url,[\s\S]*?^\s{2}\}', self.studio_app, re.MULTILINE)
        self.assertIsNotNone(lb_studio_match)
        lb_studio = lb_studio_match.group(0)
        self.assertIn("hw-modal-lightbox-container", lb_studio)
        self.assertIn("hw-modal-lightbox-img", lb_studio)
        self.assertIn("查看原图", lb_studio)
        self.assertNotIn("style=\"max-height:74vh", lb_studio)

        # forum-app.js openImageLightboxModal uses shared lightbox classes and provides view original link
        lb_forum_match = re.search(r'function openImageLightboxModal\(src,[\s\S]*?^\s{2}\}', self.forum_app, re.MULTILINE)
        self.assertIsNotNone(lb_forum_match)
        lb_forum = lb_forum_match.group(0)
        self.assertIn("hw-modal-lightbox-container", lb_forum)
        self.assertIn("hw-modal-lightbox-img", lb_forum)
        self.assertIn("查看原图", lb_forum)
        self.assertNotIn("style=\"max-width:100%;max-height:76vh", lb_forum)

    def test_04_broken_image_placeholder(self):
        """Broken or failed images must have visible placeholder styles."""
        self.assertIn(".hw-img-broken", self.theme_css)
        self.assertIn("hw-img-failed", self.theme_css)


if __name__ == "__main__":
    unittest.main()
