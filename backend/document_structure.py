"""Document structure extractor for Handraw Web 2.0 (C3, S4).

Extracts ordered structural blocks (headings, paragraphs, lists, tables, images)
from docx, pdf, md, txt, and legacy doc files with strict resource boundaries.
"""
from __future__ import annotations

import collections
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_UNCOMPRESSED_DOCX_BYTES = 50 * 1024 * 1024  # 50MB
MAX_PDF_PAGES = 300
MAX_EXTRACTED_CHARS = 200_000
MAX_EXTRACTED_IMAGES = 50
MAX_SINGLE_IMAGE_BYTES = 15 * 1024 * 1024  # 15MB


class DocumentImportError(Exception):
    """Raised when an uploaded document fails structural validation or limits."""


def _detect_format(file_bytes: bytes, filename: str = "") -> str:
    lower_name = (filename or "").lower()
    if lower_name.endswith(".docx") or (file_bytes.startswith(b"PK\x03\x04") and not lower_name.endswith(".zip")):
        return "docx"
    if lower_name.endswith(".pdf") or file_bytes.startswith(b"%PDF-"):
        return "pdf"
    if lower_name.endswith(".md"):
        return "md"
    if lower_name.endswith(".txt"):
        return "txt"
    if lower_name.endswith(".rtf") or file_bytes.startswith(b"{\\rtf"):
        return "rtf"
    if lower_name.endswith(".doc") or file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc"
    return "unknown"


def extract_document_structure(file_bytes: bytes, filename: str = "") -> dict[str, Any]:
    """Parse document into an ordered list of blocks and extracted images."""
    if not file_bytes:
        raise DocumentImportError("文件内容为空")

    fmt = _detect_format(file_bytes, filename)
    if fmt == "rtf" or fmt == "unknown":
        raise DocumentImportError("暂不支持该格式")

    blocks: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    legacy_format = False

    if fmt == "docx":
        blocks, images = _extract_docx(file_bytes)
    elif fmt == "pdf":
        blocks, images = _extract_pdf(file_bytes)
    elif fmt == "md":
        blocks, images = _extract_markdown(file_bytes)
    elif fmt == "txt":
        blocks = _extract_txt(file_bytes)
    elif fmt == "doc":
        blocks = _extract_legacy_doc(file_bytes, filename)
        legacy_format = True

    # Global boundary validations
    if len(images) > MAX_EXTRACTED_IMAGES:
        raise DocumentImportError("抽取图片超过50张限制")

    total_chars = 0
    for b in blocks:
        if b.get("text"):
            total_chars += len(b["text"])
        if b.get("type") == "table" and b.get("rows"):
            for row in b["rows"]:
                for cell in row:
                    total_chars += len(cell)

    if total_chars > MAX_EXTRACTED_CHARS:
        raise DocumentImportError("抽取字符总数超过200,000限制")

    return {
        "blocks": blocks,
        "images": images,
        "legacy_format": legacy_format,
    }


def _extract_docx(file_bytes: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Check uncompressed size
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            uncompressed = sum(info.file_size for info in zf.infolist())
            if uncompressed > MAX_UNCOMPRESSED_DOCX_BYTES:
                raise DocumentImportError("docx解压后大小超过50MB限制")
    except zipfile.BadZipFile as exc:
        raise DocumentImportError("无效的 DOCX 文件结构") from exc

    import docx

    try:
        doc = docx.Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise DocumentImportError(f"DOCX 文件解析失败: {exc}") from exc

    blocks: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    # Iterate through body elements in document order
    for child in doc.element.body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = docx.text.paragraph.Paragraph(child, doc)
            # Check for inline drawings/images inside this paragraph
            blips = child.xpath(".//*[local-name()='blip']")
            for blip in blips:
                r_id = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                if not r_id:
                    for k, v in blip.attrib.items():
                        if k.endswith("embed"):
                            r_id = v
                            break
                if r_id and r_id in doc.part.related_parts:
                    img_part = doc.part.related_parts[r_id]
                    img_bytes = img_part.image.blob
                    if len(img_bytes) > MAX_SINGLE_IMAGE_BYTES:
                        raise DocumentImportError("单张图片超过15MB限制")
                    img_idx = len(images) + 1
                    ref = f"upload:{img_idx}"
                    mime = getattr(img_part, "content_type", "image/png")
                    images.append({"ref": ref, "bytes": img_bytes, "mime": mime})
                    blocks.append({"type": "image", "image_ref": ref, "image_bytes": img_bytes, "mime": mime})

            text = (p.text or "").strip()
            if not text:
                continue

            # Determine paragraph style / heading level / list
            style_name = (p.style.name if p.style else "").lower()
            outline_lvls = child.xpath(".//w:outlineLvl/@w:val")
            num_prs = child.xpath(".//w:numPr")

            level = 0
            if outline_lvls:
                try:
                    level = int(outline_lvls[0]) + 1
                except (ValueError, TypeError):
                    level = 0

            if not level:
                m_h = re.search(r"(?:heading|标题)\s*(\d)", style_name)
                if m_h:
                    level = int(m_h.group(1))
                elif "title" in style_name:
                    level = 1
                elif "subtitle" in style_name:
                    level = 2

            if level > 0:
                blocks.append({"type": "heading", "level": min(6, max(1, level)), "text": text})
            elif num_prs or "list" in style_name or "列表" in style_name:
                blocks.append({"type": "list_item", "text": text})
            else:
                blocks.append({"type": "paragraph", "text": text})

        elif tag == "tbl":
            table = docx.table.Table(child, doc)
            rows: list[list[str]] = []
            table_images: list[dict[str, Any]] = []

            def _inspect_cell_for_images(cell_element):
                blips = cell_element.xpath(".//*[local-name()='blip']")
                for blip in blips:
                    r_id = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                    if not r_id:
                        for k, v in blip.attrib.items():
                            if k.endswith("embed"):
                                r_id = v
                                break
                    if r_id and r_id in doc.part.related_parts:
                        img_part = doc.part.related_parts[r_id]
                        img_bytes = img_part.image.blob
                        if len(img_bytes) > MAX_SINGLE_IMAGE_BYTES:
                            raise DocumentImportError("单张图片超过15MB限制")
                        img_idx = len(images) + 1
                        ref = f"upload:{img_idx}"
                        mime = getattr(img_part, "content_type", "image/png")
                        img_info = {"ref": ref, "bytes": img_bytes, "mime": mime}
                        images.append(img_info)
                        table_images.append({
                            "type": "image",
                            "image_ref": ref,
                            "image_bytes": img_bytes,
                            "mime": mime,
                        })

            for row in table.rows:
                row_cells = []
                for c in row.cells:
                    _inspect_cell_for_images(c._tc)
                    row_cells.append(c.text.strip())
                rows.append(row_cells)

            if any(any(c for c in r) for r in rows):
                blocks.append({"type": "table", "rows": rows})
            for t_img in table_images:
                blocks.append(t_img)

    return blocks, images


def _extract_pdf(file_bytes: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise DocumentImportError(f"PDF 文件解析失败: {exc}") from exc

    if len(doc) > MAX_PDF_PAGES:
        raise DocumentImportError("PDF页数超过300页限制")

    # Check for scanned PDF (no selectable text across all pages)
    total_raw_text = "".join(page.get_text("text") for page in doc).strip()
    if not total_raw_text:
        raise DocumentImportError("暂不支持扫描版 PDF")

    # Pass 1: compute dominant body font size
    size_counts: collections.Counter[float] = collections.Counter()
    for page in doc:
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            if b.get("type") == 0:
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        stext = span.get("text", "").strip()
                        if stext:
                            size = round(span.get("size", 11.0), 1)
                            size_counts[size] += len(stext)

    body_size = 11.0
    if size_counts:
        body_size = size_counts.most_common(1)[0][0]

    blocks: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    # Pass 2: extract blocks in visual reading order
    for page in doc:
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            btype = b.get("type", 0)
            if btype == 0:  # text
                lines = b.get("lines", [])
                spans_in_block = [s for l in lines for s in l.get("spans", []) if s.get("text", "").strip()]
                if not spans_in_block:
                    continue

                # Merge lines into block text
                line_texts: list[str] = []
                for l in lines:
                    lt = "".join(s.get("text", "") for s in l.get("spans", [])).strip()
                    if lt:
                        line_texts.append(lt)
                block_text = " ".join(line_texts).strip()
                if not block_text:
                    continue

                max_size = max(s.get("size", body_size) for s in spans_in_block)
                is_bold = any(
                    (s.get("flags", 0) & 2 or (s.get("flags", 0) & 16) or "bold" in str(s.get("font", "")).lower())
                    for s in spans_in_block
                )

                # Heading inference
                if len(block_text) < 120 and (max_size >= body_size * 1.15 or (is_bold and max_size >= body_size)):
                    if max_size >= body_size * 1.4:
                        level = 1
                    elif max_size >= body_size * 1.2:
                        level = 2
                    else:
                        level = 3
                    blocks.append({"type": "heading", "level": level, "text": block_text})
                elif block_text.startswith(("- ", "* ", "• ", "1. ", "2. ", "3. ")):
                    clean_item = re.sub(r"^[-*•]\s+|\d+\.\s+", "", block_text).strip()
                    blocks.append({"type": "list_item", "text": clean_item})
                else:
                    blocks.append({"type": "paragraph", "text": block_text})

            elif btype == 1:  # image
                img_bytes = b.get("image")
                ext = str(b.get("ext") or "png").lower()
                if img_bytes:
                    if len(img_bytes) > MAX_SINGLE_IMAGE_BYTES:
                        raise DocumentImportError("单张图片超过15MB限制")
                    img_idx = len(images) + 1
                    ref = f"upload:{img_idx}"
                    mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
                    images.append({"ref": ref, "bytes": img_bytes, "mime": mime})
                    blocks.append({"type": "image", "image_ref": ref, "image_bytes": img_bytes, "mime": mime})

    return blocks, images


def _extract_markdown(file_bytes: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # 1. Heading
        m_h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m_h:
            blocks.append({"type": "heading", "level": len(m_h.group(1)), "text": m_h.group(2).strip()})
            i += 1
            continue

        # 2. Table
        if line.startswith("|") and line.endswith("|"):
            table_lines: list[str] = []
            while i < n and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            rows: list[list[str]] = []
            for tl in table_lines:
                # Skip separator line like |---|---|
                if re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", tl):
                    continue
                cells = [c.strip() for c in tl.strip("|").split("|")]
                rows.append(cells)
            if rows:
                blocks.append({"type": "table", "rows": rows})
            continue

        # 3. List Item
        m_li = re.match(r"^(?:[-*+]|\d+\.)\s+(.*)$", line)
        if m_li:
            blocks.append({"type": "list_item", "text": m_li.group(1).strip()})
            i += 1
            continue

        # 4. Standalone Image
        m_img = re.match(r"^!\[(.*?)\]\((.*?)\)$", line)
        if m_img:
            img_ref = m_img.group(2).strip()
            blocks.append({"type": "paragraph", "text": line})
            i += 1
            continue

        # 5. Regular paragraph (accumulate contiguous lines)
        para_lines = [line]
        i += 1
        while i < n and lines[i].strip() and not lines[i].strip().startswith(("#", "|", "- ", "* ", "+ ")) and not re.match(r"^\d+\.\s+", lines[i].strip()):
            para_lines.append(lines[i].strip())
            i += 1
        blocks.append({"type": "paragraph", "text": "\n".join(para_lines)})

    return blocks, images


def _extract_txt(file_bytes: bytes) -> list[dict[str, Any]]:
    # Decode with common encodings
    text = ""
    for enc in ["utf-8", "utf-8-sig", "gb18030", "gbk", "utf-16le"]:
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = file_bytes.decode("utf-8", errors="replace")

    chunks = re.split(r"\n\s*\n", text)
    blocks: list[dict[str, Any]] = []
    for chunk in chunks:
        c = chunk.strip()
        if c:
            blocks.append({"type": "paragraph", "text": c})
    return blocks


def _extract_legacy_doc(file_bytes: bytes, filename: str = "") -> list[dict[str, Any]]:
    from backend.document_parser import extract_text_from_file

    raw_text = extract_text_from_file(file_bytes, filename)
    chunks = re.split(r"\n\s*\n", raw_text)
    blocks: list[dict[str, Any]] = []
    for chunk in chunks:
        c = chunk.strip()
        if c:
            blocks.append({"type": "paragraph", "text": c})
    return blocks
