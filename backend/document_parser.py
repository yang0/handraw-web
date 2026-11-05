"""Document parser and AI article extraction service for Handraw Web 2.0.

Supports:
- Markdown (.md)
- Plain text (.txt)
- Microsoft Word (.docx, .doc, .rtf)
- Adobe PDF (.pdf)

Uses local AI configuration (ai-service.json) to structure raw text into
standard title and Markdown body.
"""
from __future__ import annotations

import io
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict

from backend import ai_client
from backend.config import load_ai_config

logger = logging.getLogger(__name__)


def _extract_text_runs(text: str, min_len: int = 4) -> str:
    """Extract sequences of readable characters from decoded binary streams."""
    if not text:
        return ""
    # Chinese characters, alphanumeric, common punctuation and whitespace
    pattern = re.compile(r"[\u4e00-\u9fa5a-zA-Z0-9，。！？、：；“”‘’（）《》【】\s\n\r\t\-—·]{" + str(min_len) + r",}")
    runs = pattern.findall(text)
    clean_runs = [r.strip() for r in runs if len(r.strip()) >= min_len]
    return "\n\n".join(clean_runs)


def extract_text_from_file(file_bytes: bytes, filename: str = "") -> str:
    """Extract plain text from uploaded binary documents (.md, .txt, .docx, .doc, .pdf)."""
    if not file_bytes:
        return ""

    lower_name = (filename or "").lower()

    # 1. PDF Documents
    if lower_name.endswith(".pdf") or file_bytes.startswith(b"%PDF-"):
        try:
            try:
                import pymupdf as fitz  # Modern PyMuPDF name; avoids deprecated fitz warning.
            except ImportError:
                import fitz  # Compatibility with older PyMuPDF installations.

            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages_text = []
            for page in doc:
                t = page.get_text("text")
                if t:
                    pages_text.append(t)
            extracted = "\n\n".join(pages_text).strip()
            if extracted:
                logger.info("Extracted %d chars from PDF via PyMuPDF", len(extracted))
                return extracted
        except Exception as e:
            logger.warning("PyMuPDF extraction failed: %s; trying pdfplumber", e)

        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages_text = []
                for p in pdf.pages:
                    t = p.extract_text()
                    if t:
                        pages_text.append(t)
                extracted = "\n\n".join(pages_text).strip()
                if extracted:
                    logger.info("Extracted %d chars from PDF via pdfplumber", len(extracted))
                    return extracted
        except Exception as e:
            logger.warning("pdfplumber extraction failed: %s", e)

    # 2. DOCX / DOC Documents
    if lower_name.endswith(".docx") or lower_name.endswith(".doc") or file_bytes.startswith(b"PK\x03\x04") or file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        # 2.1 Check if file is ZIP-based (.docx format or renamed .doc)
        if file_bytes.startswith(b"PK\x03\x04") or lower_name.endswith(".docx"):
            try:
                import docx

                doc = docx.Document(io.BytesIO(file_bytes))
                parts = []
                for p in doc.paragraphs:
                    text = (p.text or "").strip()
                    if not text:
                        continue
                    style_name = (p.style.name if p.style else "").lower()
                    if "heading 1" in style_name:
                        parts.append(f"# {text}")
                    elif "heading 2" in style_name:
                        parts.append(f"## {text}")
                    elif "heading 3" in style_name:
                        parts.append(f"### {text}")
                    else:
                        parts.append(text)

                for table in doc.tables:
                    for row in table.rows:
                        row_cells = [c.text.strip() for c in row.cells if c.text.strip()]
                        if row_cells:
                            parts.append(" | ".join(row_cells))

                extracted = "\n\n".join(parts).strip()
                if extracted:
                    logger.info("Extracted %d chars from DOCX via python-docx", len(extracted))
                    return extracted
            except Exception as e:
                logger.warning("docx extraction failed: %s", e)

        # 2.2 Check if file is RTF
        if file_bytes.startswith(b"{\\rtf"):
            try:
                rtf_raw = file_bytes.decode("utf-8", errors="ignore")
                clean = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", rtf_raw)
                clean = re.sub(r"\s+", " ", clean).strip()
                if len(clean) > 20:
                    logger.info("Extracted %d chars from RTF document", len(clean))
                    return clean
            except Exception:
                pass

        # 2.3 Check if file is HTML saved as .doc
        if b"<html" in file_bytes[:1024].lower() or b"<!doctype html" in file_bytes[:1024].lower():
            try:
                for enc in ["utf-8", "gb18030", "gbk"]:
                    try:
                        html_text = file_bytes.decode(enc)
                        clean = re.sub(r"<style[\s\S]*?</style>|<script[\s\S]*?</script>|<[^>]+>", " ", html_text)
                        clean = re.sub(r"\s+", " ", clean).strip()
                        if len(clean) > 20:
                            logger.info("Extracted %d chars from HTML document", len(clean))
                            return clean
                    except UnicodeDecodeError:
                        continue
            except Exception:
                pass

        # 2.4 Binary Word 97-2003 OLE2 (.doc)
        # In CFBF format, document text is stored in streams as either UTF-16LE or GB18030/CP1252.
        # We extract printable runs from both candidate decodings and pick the richer candidate.
        candidates = []
        try:
            u16_str = file_bytes.decode("utf-16le", errors="ignore")
            u16_runs = _extract_text_runs(u16_str, min_len=4)
            if u16_runs:
                candidates.append((len(u16_runs), u16_runs))
        except Exception as e:
            logger.debug("UTF-16LE extraction error: %s", e)

        try:
            gb_str = file_bytes.decode("gb18030", errors="ignore")
            gb_runs = _extract_text_runs(gb_str, min_len=4)
            if gb_runs:
                candidates.append((len(gb_runs), gb_runs))
        except Exception as e:
            logger.debug("GB18030 extraction error: %s", e)

        try:
            u8_str = file_bytes.decode("utf-8", errors="ignore")
            u8_runs = _extract_text_runs(u8_str, min_len=4)
            if u8_runs:
                candidates.append((len(u8_runs), u8_runs))
        except Exception as e:
            logger.debug("UTF-8 extraction error: %s", e)

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_len, best_text = candidates[0]
            if best_len >= 30:
                logger.info("Extracted %d chars from binary .doc via binary stream extraction", best_len)
                return best_text

    # 3. Plain Text / Markdown / Plain Text fallbacks
    for enc in ["utf-8", "utf-8-sig", "gb18030", "gbk", "utf-16le", "utf-16be", "big5"]:
        try:
            decoded = file_bytes.decode(enc).strip()
            # Verify if it looks like actual text rather than binary gibberish
            printable_ratio = sum(1 for c in decoded if c.isprintable() or c in "\n\r\t") / max(1, len(decoded))
            if printable_ratio > 0.8:
                logger.info("Decoded %d chars with encoding %s", len(decoded), enc)
                return decoded
        except UnicodeDecodeError:
            continue

    fallback_decoded = file_bytes.decode("utf-8", errors="ignore").strip()
    return _extract_text_runs(fallback_decoded, min_len=4) or fallback_decoded


def fallback_parse_article(
    raw_text: str,
    filename: str = "",
    *,
    fallback_reason: str = "no_key",
    truncated: bool = False,
) -> Dict[str, Any]:
    """Fallback parser when AI service is unavailable."""
    clean = (raw_text or "").strip()
    if not clean:
        title = (filename.rsplit(".", 1)[0] if "." in filename else filename) or "未命名文章"
        res: Dict[str, Any] = {
            "title": title,
            "markdown": f"# {title}\n\n请在此输入正文内容…",
            "aiUsed": False,
            "fallbackReason": fallback_reason,
        }
        if truncated:
            res["truncated"] = True
        return res

    lines = [l.strip() for l in clean.splitlines() if l.strip()]
    first_line = lines[0] if lines else "未命名文章"
    first_line_clean = re.sub(r"^#+\s*", "", first_line).strip()
    title = first_line_clean[:40] if first_line_clean else "未命名文章"

    if not clean.startswith("#"):
        markdown_body = f"# {title}\n\n{clean}"
    else:
        markdown_body = clean

    res = {
        "title": title,
        "markdown": markdown_body,
        "aiUsed": False,
        "fallbackReason": fallback_reason,
    }
    if truncated:
        res["truncated"] = True
    return res


def ai_parse_article(raw_text: str, filename: str = "") -> Dict[str, Any]:
    """Call local AI service to extract a clean title and Markdown content."""
    clean_raw = (raw_text or "").strip()
    if not clean_raw:
        return fallback_parse_article(raw_text, filename, fallback_reason="empty", truncated=False)

    max_input_chars = 32000
    truncated = len(clean_raw) > max_input_chars
    if truncated:
        clean_raw = clean_raw[:max_input_chars] + "\n\n[正文文本过长，已截断]"

    doc_hint = f"（文件名：{filename}）" if filename else ""
    user_instruction = (
        "你是一个专业的出版级长文排版与章节结构拆分助手。请从给定的文档中提取文章最准确精炼的主标题（title），"
        "并将正文排版为规范的 Markdown（markdown）。\n"
        "排版规范：\n"
        "1. 一级标题为文章主标题：# 主标题\n"
        "2. 导言或摘要自然成段\n"
        "3. 核心章节使用二级标题：## 章节名\n"
        "4. 子节使用三级标题：### 小节名\n"
        "5. 重点内容使用列表或加粗，过滤页眉页脚与乱码噪音\n\n"
        "【重要】你必须严格只返回包含 `title` 和 `markdown` 两个键的合法 JSON 对象，绝不要输出任何多余的说明、分析或问候语！\n"
        'JSON 格式示例：{"title": "文章主标题", "markdown": "# 文章主标题\\n\\n正文内容..."}\n\n'
        f"待解析文档内容{doc_hint}：\n{clean_raw}"
    )

    messages = [
        {
            "role": "user",
            "content": user_instruction,
        },
    ]

    content, meta = ai_client.chat(
        messages,
        temperature=0.1,
        timeout=35,
        json_mode=True,
    )

    if not meta.get("ok"):
        reason = meta.get("reason")
        if reason == "no_key":
            logger.info("No AI key configured; using heuristic parsing for '%s'", filename)
            return fallback_parse_article(clean_raw, filename, fallback_reason="no_key", truncated=truncated)
        logger.warning("AI parse failed (%s); falling back to heuristic parsing", reason)
        return fallback_parse_article(clean_raw, filename, fallback_reason="timeout_or_error", truncated=truncated)

    try:
        content_clean = content.strip()
        if content_clean.startswith("```"):
            content_clean = re.sub(r"^```(?:json)?\s*", "", content_clean)
            content_clean = re.sub(r"\s*```$", "", content_clean)

        json_match = re.search(r"\{[\s\S]*\}", content_clean)
        if json_match:
            content_clean = json_match.group(0)

        try:
            parsed = json.loads(content_clean)
        except Exception:
            logger.warning("AI parse returned non-JSON content; falling back to heuristic parsing")
            return fallback_parse_article(clean_raw, filename, fallback_reason="invalid_json", truncated=truncated)

        if isinstance(parsed, dict):
            title = str(parsed.get("title") or "").strip()
            markdown = str(parsed.get("markdown") or "").strip()
            if title and markdown:
                logger.info("AI parsing succeeded! Extracted title: '%s', Markdown length: %d", title, len(markdown))
                res = {"title": title, "markdown": markdown, "aiUsed": True, "fallbackReason": ""}
                if truncated:
                    res["truncated"] = True
                return res
            else:
                return fallback_parse_article(clean_raw, filename, fallback_reason="empty", truncated=truncated)
        else:
            return fallback_parse_article(clean_raw, filename, fallback_reason="invalid_json", truncated=truncated)
    except Exception as e:
        logger.warning("AI parse processing failed (%s); falling back to heuristic parsing", e)
        return fallback_parse_article(clean_raw, filename, fallback_reason="timeout_or_error", truncated=truncated)


def _strip_duplicate_heading(markdown: str, title: str) -> str:
    """Drop a leading H1 that merely repeats the title already shown above it.

    The structuring prompt asks for the heading inside the markdown, but the
    editor renders the title in its own field, so keeping both showed it twice.
    """
    lines = str(markdown or "").split("\n")
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return markdown
    first = lines[idx].strip()
    if not first.startswith("# ") or first.startswith("## "):
        return markdown
    if first[2:].strip() != str(title or "").strip():
        return markdown
    rest = lines[idx + 1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return "\n".join(rest)


def parse_article_file(file_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """Complete entrypoint: extract document text and run AI structuring."""
    raw_text = extract_text_from_file(file_bytes, filename)
    result = ai_parse_article(raw_text, filename)
    result["markdown"] = _strip_duplicate_heading(result.get("markdown", ""), result.get("title", ""))
    result["fileName"] = filename
    result["rawLength"] = len(raw_text)
    return result
