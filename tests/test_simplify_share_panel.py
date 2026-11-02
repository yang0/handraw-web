"""Test share panel simplification and modal image aspect-ratio."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def test_share_panel_single_copy_button():
    shared_js = (REPO_ROOT / "demo" / "assets" / "shared.js").read_text(encoding="utf-8")
    # Must NOT have data-btn-share-card-forum
    assert 'data-btn-share-card-forum' not in shared_js
    # Must have copy button
    assert 'data-btn-copy-share="1"' in shared_js
    assert '📋 复制分享口令' in shared_js
    # Must have topic permalink url
    assert 'https://handraw-style.com/t/' in shared_js
    # Must have hw-share-thumb-wrap
    assert 'hw-share-thumb-wrap' in shared_js

def test_no_inline_modal_cropping():
    shared_js = (REPO_ROOT / "demo" / "assets" / "shared.js").read_text(encoding="utf-8")
    assert 'height:125px;object-fit:cover' not in shared_js
    assert 'height:120px;object-fit:cover' not in shared_js
    assert 'height:96px;object-fit:cover' not in shared_js
    assert 'hw-picker-card-media' in shared_js

def test_theme_css_scoped_picker_and_responsive():
    theme_css = (REPO_ROOT / "demo" / "assets" / "theme.css").read_text(encoding="utf-8")
    assert '.hw-picker-card-media' in theme_css
    assert 'aspect-ratio: 1 / 1;' in theme_css
    assert '.hw-share-thumb-wrap' in theme_css
    assert '.hw-btn-copy-share' in theme_css
