"""Importing a document must land the text in the editor, and the title once."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.document_parser import _strip_duplicate_heading, parse_article_file


def test_leading_heading_that_repeats_the_title_is_dropped():
    assert _strip_duplicate_heading("# 标题\n\n正文内容。", "标题") == "正文内容。"


def test_leading_heading_is_kept_when_it_differs_from_the_title():
    assert _strip_duplicate_heading("# 另一个\n\n正文", "标题") == "# 另一个\n\n正文"


def test_deeper_headings_are_never_touched():
    assert _strip_duplicate_heading("## 小节\n\n正文", "小节") == "## 小节\n\n正文"


def test_body_without_a_heading_is_unchanged():
    assert _strip_duplicate_heading("正文直接开始", "标题") == "正文直接开始"


def test_blank_lines_after_the_heading_are_dropped_too():
    assert _strip_duplicate_heading("# 标题\n\n\n正文", "标题") == "正文"


def test_parse_returns_the_body_without_the_repeated_title(monkeypatch):
    import backend.document_parser as dp

    monkeypatch.setattr(dp, "extract_text_from_file", lambda *a, **k: "标题\n正文")
    monkeypatch.setattr(dp, "ai_parse_article", lambda *a, **k: {"title": "标题", "markdown": "# 标题\n\n正文"})
    result = parse_article_file(b"x", "t.md")
    assert result["title"] == "标题"
    assert result["markdown"] == "正文"
