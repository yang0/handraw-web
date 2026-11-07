"""Asynchronous document importer service for Handraw Web 2.0 (C4, C5, S4, S5).

Handles chunked AI structuring, fidelity verification, image isolation,
bounded queue with two worker threads, watchdog deadline enforcement, and media cleanup.
"""
from __future__ import annotations

import collections
import io
import json
import logging
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend import ai_client
from backend.config import get_uploads_dir
from backend.db import Database, utc_now_iso
from backend.document_structure import DocumentImportError, extract_document_structure
from backend.runtime_policy import validate_image_bytes

logger = logging.getLogger(__name__)

MAX_JOB_DURATION_SECONDS = 600.0  # 10 minutes hard deadline
SEGMENT_CHAR_LIMIT = 6000

AI_SEGMENT_SYSTEM_PROMPT = (
    "你是一个专业的出版级长文排版与结构整理助手。请对给定的正文内容进行 Markdown 排版。\n"
    "排版规范与严格约束：\n"
    "1. 【核心原则】严禁改写、删减或增补原文中的任何文字和句子！必须完整保留原作者的所有表达。\n"
    "2. 只做标题分级（使用 #, ##, ### 等）、合并错误断行、去除页眉页脚与孤立页码。\n"
    "3. 将表格内容整理为标准的 Markdown 表格。\n"
    "4. 文中的图片占位符 ![](upload:<n>) 必须原样保留在原位置，绝对不得遗漏或更改编号！\n"
    "5. 严格只输出纯 Markdown 内容，绝不要包含代码块标记（不要用 ```markdown 包裹），绝不要输出任何解释、说明或问候语。"
)


def _format_table_as_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    if col_count == 0:
        return ""
    norm_rows: list[list[str]] = []
    for r in rows:
        norm = [c.replace("\n", " ").replace("|", "\\|").strip() for c in r]
        norm += [""] * (col_count - len(norm))
        norm_rows.append(norm)

    header = norm_rows[0]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for r in norm_rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _block_to_local_markdown(b: dict[str, Any]) -> str:
    btype = b.get("type")
    if btype == "heading":
        lvl = b.get("level", 1)
        return f"{'#' * lvl} {b.get('text', '')}"
    if btype == "paragraph":
        return str(b.get("text", ""))
    if btype == "list_item":
        return f"- {b.get('text', '')}"
    if btype == "table":
        return _format_table_as_markdown(b.get("rows", []))
    if btype == "image":
        ref = b.get("image_ref") or "upload:1"
        return f"![]({ref})"
    return str(b.get("text", ""))


def _strip_markdown(text: str) -> str:
    """Strip Markdown syntax while preserving textual and code contents for fidelity check."""
    # Strip code block fences but keep the internal code contents
    s = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", text)
    s = s.replace("```", "")
    s = s.replace("`", "")
    s = re.sub(r"!\[.*?\]\((?:upload:\d+|[^\)]+)\)", "", s)
    s = re.sub(r"\[(.*?)\]\([^\)]+\)", r"\1", s)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"[*_~|>]", " ", s)
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\d+\.\s+", "", s, flags=re.MULTILINE)
    return s


def _extract_cjk_and_alnum(text: str) -> str:
    """Return sequence of Chinese characters and alphanumeric characters."""
    chars = re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]", text)
    return "".join(chars)


def _normalize_and_split_huge_block(
    b: dict[str, Any],
    max_len: int = 5000,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Enforce that no single block exceeds max_len, splitting large paragraphs, lists, headings, and tables."""
    btype = b.get("type")

    if btype in ("paragraph", "list_item"):
        text = str(b.get("text") or "")
        if len(text) <= max_len:
            return [b]

        chunks: list[str] = []
        while len(text) > max_len:
            split_idx = -1
            for sep in ["\n\n", "\n", "。", "！", "？", "；", " ", "\t"]:
                pos = text.rfind(sep, 0, max_len)
                if pos > max_len // 2:
                    split_idx = pos + len(sep)
                    break
            if split_idx == -1:
                split_idx = max_len
            chunks.append(text[:split_idx])
            text = text[split_idx:]
        if text:
            chunks.append(text)
        return [{"type": btype, "text": c} for c in chunks if c]

    elif btype == "table":
        rows = b.get("rows", [])
        if not rows:
            return [b]

        header = rows[0]
        data_rows = rows[1:]

        # S4: Check if header itself exceeds max_len
        header_md = _format_table_as_markdown([header])
        header_exceeded = (len(header_md) > max_len) or any(len(c) > max_len for c in header)

        output_blocks: list[dict[str, Any]] = []

        if header_exceeded:
            if warnings is not None and "table_row_too_long" not in warnings:
                warnings.append("table_row_too_long")
            # Expand header row into paragraph text
            header_text = "\n".join(f"列{i+1}：{c}" if c else "" for i, c in enumerate(header)).strip()
            if not header_text:
                header_text = "\n".join(c for c in header if c)
            output_blocks.extend(
                _normalize_and_split_huge_block(
                    {"type": "paragraph", "text": header_text}, max_len=max_len, warnings=warnings
                )
            )
            effective_header = None
        else:
            effective_header = header

        cur_sub_rows: list[list[str]] = [effective_header] if effective_header else []
        cur_len = len(_format_table_as_markdown(cur_sub_rows)) if cur_sub_rows else 0

        for row in data_rows:
            row_md = "| " + " | ".join(c.replace("\n", " ").replace("|", "\\|") for c in row) + " |\n"
            row_len = len(row_md)

            # V2: Check whether this row alone, OR (header + separator + row) combined, exceeds max_len
            if effective_header:
                single_row_tbl_len = len(_format_table_as_markdown([effective_header, row]))
                row_exceeded = (single_row_tbl_len > max_len) or any(len(c) > max_len for c in row)
            else:
                row_exceeded = (row_len > max_len) or any(len(c) > max_len for c in row)

            if row_exceeded:
                if warnings is not None and "table_row_too_long" not in warnings:
                    warnings.append("table_row_too_long")
                # Flush existing table rows if any
                if cur_sub_rows and (len(cur_sub_rows) > 1 if effective_header else len(cur_sub_rows) > 0):
                    output_blocks.append({"type": "table", "rows": cur_sub_rows})
                    cur_sub_rows = [effective_header] if effective_header else []
                    cur_len = len(_format_table_as_markdown(cur_sub_rows)) if cur_sub_rows else 0

                # Expand this row into paragraph text (列名：内容)
                if effective_header:
                    row_text = "\n".join(
                        f"{effective_header[i]}：{row[i]}" if i < len(effective_header) else str(row[i])
                        for i in range(len(row))
                    )
                else:
                    row_text = "\n".join(str(c) for c in row if c)

                output_blocks.extend(
                    _normalize_and_split_huge_block(
                        {"type": "paragraph", "text": row_text}, max_len=max_len, warnings=warnings
                    )
                )
            else:
                candidate_rows = cur_sub_rows + [row]
                candidate_len = len(_format_table_as_markdown(candidate_rows))
                min_rows = 1 if effective_header else 0
                if candidate_len > max_len and len(cur_sub_rows) > min_rows:
                    output_blocks.append({"type": "table", "rows": cur_sub_rows})
                    cur_sub_rows = [effective_header, row] if effective_header else [row]
                    cur_len = len(_format_table_as_markdown(cur_sub_rows))
                else:
                    cur_sub_rows.append(row)
                    cur_len = candidate_len

        if cur_sub_rows and (len(cur_sub_rows) > 1 if effective_header else len(cur_sub_rows) > 0):
            output_blocks.append({"type": "table", "rows": cur_sub_rows})

        return output_blocks if output_blocks else [b]

    elif btype == "heading":
        text = str(b.get("text") or "")
        if len(text) > max_len:
            if warnings is not None and "heading_too_long" not in warnings:
                warnings.append("heading_too_long")
            # S3: Convert super-long heading to paragraph block and split losslessly
            para_block = {"type": "paragraph", "text": text}
            return _normalize_and_split_huge_block(para_block, max_len=max_len, warnings=warnings)
        return [b]

    return [b]


def split_blocks_into_segments(
    blocks: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> list[list[dict[str, Any]]]:
    """Split blocks into chunks of <= 6000 chars, starting new segments at headings."""
    norm_blocks: list[dict[str, Any]] = []
    for b in blocks:
        norm_blocks.extend(_normalize_and_split_huge_block(b, max_len=5000, warnings=warnings))

    segments: list[list[dict[str, Any]]] = []
    current_segment: list[dict[str, Any]] = []
    current_chars = 0

    for b in norm_blocks:
        b_md = _block_to_local_markdown(b)
        b_len = len(b_md)
        btype = b.get("type")

        is_major_heading = (btype == "heading" and b.get("level", 1) <= 2)
        separator_len = 2 if current_segment else 0
        would_overflow = (current_chars + separator_len + b_len > SEGMENT_CHAR_LIMIT and current_segment)

        if (is_major_heading or would_overflow) and current_segment:
            segments.append(current_segment)
            current_segment = []
            current_chars = 0
            separator_len = 0

        current_segment.append(b)
        current_chars += separator_len + b_len

    if current_segment:
        segments.append(current_segment)

    return segments


def verify_fidelity(
    orig_text: str,
    res_text: str,
    orig_table_cells: int = 0,
    orig_images_count: int = 0,
) -> tuple[float, list[str]]:
    """Compare original and formatted text; return (charDiffRatio, list of issues)."""
    issues: list[str] = []

    # 1. Alphanumeric + CJK character difference ratio
    orig_clean = _extract_cjk_and_alnum(_strip_markdown(orig_text))
    res_clean = _extract_cjk_and_alnum(_strip_markdown(res_text))
    orig_len = len(orig_clean)
    res_len = len(res_clean)
    diff_ratio = round(abs(orig_len - res_len) / max(1, orig_len), 4)
    if diff_ratio > 0.05:
        issues.append("possible_content_change")

    # 2. Numbers and percentages
    orig_nums = set(re.findall(r"\d+(?:\.\d+)?%?", orig_text))
    res_nums = set(re.findall(r"\d+(?:\.\d+)?%?", res_text))
    if orig_nums != res_nums:
        issues.append("numbers_mismatch")

    # 3. Formulas and mathematical symbols (× = + − ÷ % and $...$)
    formula_symbols = ["×", "=", "+", "−", "÷", "%"]
    sym_mismatch = any(orig_text.count(sym) != res_text.count(sym) for sym in formula_symbols)
    orig_latex = set(re.findall(r"\$[^\$\n]+\$", orig_text))
    res_latex = set(re.findall(r"\$[^\$\n]+\$", res_text))
    if sym_mismatch or orig_latex != res_latex:
        issues.append("formulas_mismatch")

    # 4. Images placeholder count
    res_imgs = len(re.findall(r"!\[.*?\]\((?:upload:\d+|/uploads/[^\)]+)\)", res_text))
    if orig_images_count != res_imgs:
        issues.append("images_mismatch")

    # 5. Table cells count (preserves empty cells, handles escaped pipes \|, and excludes repeated headers from chunking)
    if orig_table_cells > 0:
        orig_lines = [line.strip() for line in orig_text.splitlines()]
        orig_header_counts: dict[str, int] = {}
        for i, line in enumerate(orig_lines):
            if line.startswith("|") and line.endswith("|") and not re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", line):
                if i + 1 < len(orig_lines):
                    next_line = orig_lines[i + 1]
                    if next_line.startswith("|") and next_line.endswith("|") and re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", next_line):
                        orig_header_counts[line] = orig_header_counts.get(line, 0) + 1

        lines = [line.strip() for line in res_text.splitlines()]
        res_header_counts: dict[str, int] = {}
        res_cells = 0

        for i, line in enumerate(lines):
            if not (line.startswith("|") and line.endswith("|")):
                continue
            if re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", line):
                continue

            # Check if this row is followed by a separator row | --- | (i.e. header row)
            is_header = False
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.startswith("|") and next_line.endswith("|") and re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", next_line):
                    is_header = True

            inner = line[1:-1]
            cells = re.split(r"(?<!\\)\|", inner)

            if is_header:
                current_count = res_header_counts.get(line, 0) + 1
                res_header_counts[line] = current_count
                orig_allowed = orig_header_counts.get(line, 1)
                if current_count > orig_allowed:
                    # S9/V4: Repeated header row inserted across segment splits exceeds original count, exclude
                    continue

            res_cells += len(cells)

        if orig_table_cells != res_cells:
            issues.append("table_cells_mismatch")

    return diff_ratio, issues


def _convert_image_to_png_if_needed(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """Validate and fully decode image via Pillow, converting non-standard formats to PNG."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(image_bytes)) as pil_img:
            # S8: Fully decode pixel data (verifies IDAT chunks, checks MAX_IMAGE_PIXELS, catches corrupt streams)
            pil_img.load()
            fmt = (pil_img.format or "").upper()
            if getattr(pil_img, "is_animated", False):
                pil_img.seek(0)

            # If it's already a standard valid PNG/JPEG/WEBP, return the validated bytes
            if fmt == "PNG":
                return image_bytes, "image/png"
            elif fmt == "JPEG":
                return image_bytes, "image/jpeg"
            elif fmt == "WEBP":
                return image_bytes, "image/webp"

            # Otherwise (GIF, BMP, TIFF, etc.), convert to PNG
            mode = pil_img.mode
            conv = pil_img.convert("RGBA" if mode in ("RGBA", "LA", "P") else "RGB")
            out = io.BytesIO()
            conv.save(out, format="PNG")
            return out.getvalue(), "image/png"
    except Exception as exc:
        raise DocumentImportError(f"图片解码失败：{exc}") from exc


def save_uploaded_image_bytes(
    db: Database,
    user_id: int,
    image_bytes: bytes,
    mime: str = "",
    name_zh: str = "导入图片",
) -> str:
    """Save raw image bytes into the user's private media library, deleting file on DB failure."""
    if not mime:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif image_bytes.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            mime = "image/png"

    payload, ext = validate_image_bytes(image_bytes, mime)
    uploads_dir = get_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    up_id = f"UPL-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    fname = f"{up_id}{ext}"
    fpath = uploads_dir / fname

    public_url = f"/uploads/{fname}"
    from .media_storage import persist_media_bytes
    persist_media_bytes(public_url, payload, mime=mime)
    try:
        with db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, desc_zh, image_url, file_path, bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    up_id,
                    int(user_id),
                    "import",
                    (name_zh or "导入图片")[:60],
                    "",
                    public_url,
                    str(fpath),
                    len(payload),
                    utc_now_iso(),
                ),
            )
    except Exception:
        # File written on disk but DB registration failed: remove file immediately
        fpath.unlink(missing_ok=True)
        raise

    return public_url


def _cleanup_job_media(db: Database, user_id: int, image_urls: list[str]) -> None:
    """Clean up images associated with a failed/abandoned import job."""
    for url in image_urls:
        try:
            with db.transaction() as tx:
                row = tx.execute(
                    "SELECT id, file_path FROM user_uploads WHERE user_id = ? AND image_url = ?",
                    (user_id, url),
                ).fetchone()
                if row:
                    tx.execute("DELETE FROM user_uploads WHERE id = ?", (row["id"],))
                    from .media_gc import queue_media_cleanup
                    queue_media_cleanup(tx, url, delay_seconds=60)
        except Exception:
            pass


def mark_legacy_imports_failed(db: Database) -> int:
    """Mark any leftover queued or running import jobs as failed on server startup."""
    try:
        with db.transaction() as tx:
            cur = tx.execute(
                """
                UPDATE studio_import_jobs
                SET status = 'failed',
                    error = '服务重启，请重新导入',
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (utc_now_iso(),),
            )
            count = cur.rowcount
            if count > 0:
                logger.info("Marked %d leftover import jobs as failed on startup", count)
            return count
    except Exception as exc:
        logger.warning("Could not mark leftover import jobs failed: %s", exc)
        return 0


def cleanup_unreferenced_import_media(db: Database, max_age_hours: int = 24) -> int:
    """Clean up import images older than max_age_hours that are no longer referenced."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cleaned_count = 0

    try:
        with db.transaction() as tx:
            rows = tx.execute(
                """
                SELECT id, image_url, file_path FROM user_uploads
                WHERE cat = 'import' AND created_at < ?
                """,
                (cutoff,),
            ).fetchall()
    except Exception:
        return 0

    for row in rows:
        url = row["image_url"]
        path_str = row["file_path"]

        with db.transaction() as tx:
            ref_art = tx.execute(
                "SELECT 1 FROM studio_articles WHERE (markdown LIKE ? OR cards_json LIKE ?) AND COALESCE(deleted_at, '') = '' LIMIT 1",
                (f"%{url}%", f"%{url}%"),
            ).fetchone()
            ref_job = tx.execute(
                "SELECT 1 FROM studio_import_jobs WHERE result_json LIKE ? LIMIT 1",
                (f"%{url}%",),
            ).fetchone()

        if not ref_art and not ref_job:
            with db.transaction() as tx:
                tx.execute("DELETE FROM user_uploads WHERE id = ?", (row["id"],))
                from .media_gc import queue_media_cleanup
                queue_media_cleanup(tx, url, delay_seconds=60)
            cleaned_count += 1

    return cleaned_count


class ImportManager:
    """Manages asynchronous document imports with bounded queue, 2 worker threads, and watchdog."""

    def __init__(
        self,
        db: Database,
        max_queue: int = 20,
        num_workers: int = 2,
        watchdog_interval: float = 30.0,
    ) -> None:
        self.db = db
        self.queue: queue.Queue[tuple[str, int, str, bytes]] = queue.Queue(maxsize=max_queue)
        self.num_workers = num_workers
        self.watchdog_interval = watchdog_interval
        self.workers: list[threading.Thread] = []
        self._watchdog_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False
        self._last_media_cleanup = 0.0

    def start(self) -> "ImportManager":
        if self._started:
            return self
        self._stop.clear()
        mark_legacy_imports_failed(self.db)
        for i in range(self.num_workers):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"handraw-import-worker-{i}",
                daemon=True,
            )
            t.start()
            self.workers.append(t)

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="handraw-import-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

        self._started = True
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        for t in self.workers:
            if t.is_alive():
                t.join(timeout=max(0.1, timeout / max(1, len(self.workers))))
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=0.5)
        self.workers.clear()
        self._watchdog_thread = None
        self._started = False

        # S6: Remove stopped instance from cache
        key = str(self.db.db_path)
        with _IMPORT_MANAGERS_LOCK:
            if _IMPORT_MANAGERS.get(key) is self:
                del _IMPORT_MANAGERS[key]

    def submit_job(self, user_id: int, file_name: str, file_bytes: bytes) -> str:
        job_id = f"imp_{uuid.uuid4().hex}"
        now = utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_import_jobs
                (id, user_id, status, progress_done, progress_total, error, result_json, file_name, created_at, updated_at)
                VALUES (?, ?, 'queued', 0, 0, '', '', ?, ?, ?)
                """,
                (job_id, int(user_id), file_name or "", now, now),
            )

        try:
            self.queue.put_nowait((job_id, int(user_id), file_name, file_bytes))
        except queue.Full:
            with self.db.transaction() as tx:
                tx.execute("DELETE FROM studio_import_jobs WHERE id = ?", (job_id,))
            raise DocumentImportError("导入队列已满，请稍后再试")

        return job_id

    def enqueue_job(self, job_id: str, user_id: int, file_name: str, file_bytes: bytes) -> None:
        """Enqueue an already-persisted job row."""
        try:
            self.queue.put_nowait((job_id, int(user_id), file_name, file_bytes))
        except queue.Full as exc:
            raise DocumentImportError("导入队列已满，请稍后再试") from exc

    def _watchdog_loop(self) -> None:
        while not self._stop.is_set():
            self._check_timeouts_and_cleanup()
            self._stop.wait(self.watchdog_interval)

    def _check_timeouts_and_cleanup(self) -> None:
        # 1. Check for expired running jobs
        try:
            with self.db.transaction() as tx:
                rows = tx.execute("SELECT id, user_id, created_at, updated_at FROM studio_import_jobs WHERE status = 'running'").fetchall()
                now_dt = datetime.now(timezone.utc)
                for r in rows:
                    time_str = r["created_at"] or r["updated_at"]
                    try:
                        job_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                        if (now_dt - job_dt).total_seconds() > MAX_JOB_DURATION_SECONDS:
                            tx.execute(
                                "UPDATE studio_import_jobs SET status = 'failed', error = '处理超时', updated_at = ? WHERE id = ? AND status = 'running'",
                                (utc_now_iso(), r["id"]),
                            )
                            logger.warning("Watchdog marked job %s as failed due to timeout", r["id"])
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("Watchdog check failed: %s", exc)

        # 2. Periodic unreferenced media cleanup (once per hour)
        if time.monotonic() - self._last_media_cleanup > 3600.0:
            try:
                cleanup_unreferenced_import_media(self.db, max_age_hours=24)
                try:
                    from .user_library import cleanup_expired_library_tombstones
                    cleanup_expired_library_tombstones(self.db, max_age_days=30)
                except Exception as lib_exc:
                    logger.warning("Periodic library tombstone cleanup failed: %s", lib_exc)
                self._last_media_cleanup = time.monotonic()
            except Exception as exc:
                logger.warning("Periodic media cleanup failed: %s", exc)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            job_id, user_id, file_name, file_bytes = item
            try:
                self._process_job(job_id, user_id, file_name, file_bytes)
            except Exception as exc:
                logger.exception("Unexpected error processing import job %s: %s", job_id, exc)
                try:
                    with self.db.transaction() as tx:
                        tx.execute(
                            "UPDATE studio_import_jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                            (str(exc) or "解析失败", utc_now_iso(), job_id),
                        )
                except Exception:
                    pass
            finally:
                self.queue.task_done()
                self.db.close_thread_conn()

    def _process_job(self, job_id: str, user_id: int, file_name: str, file_bytes: bytes) -> None:
        start_time = time.monotonic()
        deadline = start_time + MAX_JOB_DURATION_SECONDS

        def _assert_not_timed_out() -> None:
            if time.monotonic() > deadline:
                raise DocumentImportError("处理超时")

        # 1. Update status to running in short transaction
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE studio_import_jobs SET status = 'running', updated_at = ? WHERE id = ?",
                (utc_now_iso(), job_id),
            )

        saved_image_urls: list[str] = []
        is_done = False

        try:
            # 2. Extract document structure (outside DB transaction)
            struct = extract_document_structure(file_bytes, file_name)

            _assert_not_timed_out()

            blocks: list[dict[str, Any]] = struct["blocks"]
            raw_images: list[dict[str, Any]] = struct["images"]
            legacy_format: bool = struct.get("legacy_format", False)

            # 3. Save images for user as private media (short transactions per image)
            image_map: dict[str, str] = {}
            image_fail_map: dict[str, str] = {}
            image_warnings: list[str] = []

            for img in raw_images:
                ref = img["ref"]
                b = img["bytes"]
                mime = img.get("mime", "")
                try:
                    conv_bytes, conv_mime = _convert_image_to_png_if_needed(b, mime)
                    public_url = save_uploaded_image_bytes(
                        self.db,
                        user_id,
                        conv_bytes,
                        mime=conv_mime,
                        name_zh=f"{Path(file_name).stem}_插图",
                    )
                    image_map[ref] = public_url
                    saved_image_urls.append(public_url)
                except Exception as exc:
                    err_msg = str(exc) or "格式无法解析"
                    logger.warning("Failed to save image %s: %s", ref, err_msg)
                    fail_desc = f"[图片未能导入：{err_msg}]"
                    image_fail_map[ref] = fail_desc
                    image_warnings.append(f"image_import_failed:{ref}:{err_msg}")

            _assert_not_timed_out()

            # 4. Split blocks into segments (enforcing <= 6000 chars per segment)
            segment_warnings: list[str] = []
            segments_blocks = split_blocks_into_segments(blocks, warnings=segment_warnings)
            total_segments = len(segments_blocks)

            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE studio_import_jobs SET progress_total = ?, progress_done = 0, updated_at = ? WHERE id = ? AND status = 'running'",
                    (total_segments, utc_now_iso(), job_id),
                )

            # 5. Process segments with AI (NO DB TRANSACTION HELD DURING AI CALLS)
            segment_results: list[dict[str, Any]] = []
            ai_failed_segments: list[int] = []
            all_orig_parts: list[str] = []
            all_res_parts: list[str] = []
            ai_success_count = 0
            ai_no_key_count = 0

            for idx, seg_blocks in enumerate(segments_blocks):
                _assert_not_timed_out()

                # Build original local markdown for this segment
                seg_orig_lines: list[str] = []
                seg_table_cells = 0
                seg_images_count = 0

                for b in seg_blocks:
                    seg_orig_lines.append(_block_to_local_markdown(b))
                    if b.get("type") == "table":
                        seg_table_cells += sum(len(r) for r in b.get("rows", []))
                    elif b.get("type") == "image":
                        seg_images_count += 1

                seg_orig_text = "\n\n".join(seg_orig_lines).strip()
                all_orig_parts.append(seg_orig_text)

                # Dynamic AI timeout bounded by job remaining time
                seg_timeout = max(0.1, min(60.0, deadline - time.monotonic()))

                # AI call
                messages = [
                    {"role": "system", "content": AI_SEGMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": seg_orig_text},
                ]
                content, meta = ai_client.chat(
                    messages,
                    temperature=0.1,
                    timeout=seg_timeout,
                    json_mode=False,
                )

                _assert_not_timed_out()

                seg_ai_used = False
                seg_res_text = ""

                if meta.get("ok") and content.strip():
                    clean_content = content.strip()
                    if clean_content.startswith("```"):
                        clean_content = re.sub(r"^```(?:markdown)?\s*", "", clean_content)
                        clean_content = re.sub(r"\s*```$", "", clean_content)
                    seg_res_text = clean_content.strip()
                    seg_ai_used = True
                    ai_success_count += 1
                else:
                    if meta.get("reason") == "no_key":
                        ai_no_key_count += 1
                    ai_failed_segments.append(idx)
                    seg_res_text = seg_orig_text

                all_res_parts.append(seg_res_text)

                # Segment fidelity check
                seg_diff, seg_issues = verify_fidelity(
                    seg_orig_text,
                    seg_res_text,
                    orig_table_cells=seg_table_cells,
                    orig_images_count=seg_images_count,
                )

                segment_results.append({
                    "index": idx,
                    "aiUsed": seg_ai_used,
                    "original": seg_orig_text,
                    "result": seg_res_text,
                    "issues": seg_issues,
                })

                # Update progress in short transaction
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE studio_import_jobs SET progress_done = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                        (idx + 1, utc_now_iso(), job_id),
                    )

            _assert_not_timed_out()

            # 6. Overall Fidelity & Result Assembly
            full_orig = "\n\n".join(all_orig_parts)
            full_res_template = "\n\n".join(all_res_parts)

            # S2: Replace image placeholders upload:(\d+)(?!\d) with regex callback to avoid prefix collisions
            def _replace_image_tag(m: re.Match) -> str:
                alt = m.group(1)
                num = m.group(2)
                ref = f"upload:{num}"
                if ref in image_map:
                    return f"![{alt}]({image_map[ref]})"
                elif ref in image_fail_map:
                    return image_fail_map[ref]
                else:
                    err_msg = "未找到对应资源"
                    image_warnings.append(f"image_import_failed:{ref}:{err_msg}")
                    return f"[图片未能导入：{err_msg}]"

            full_markdown = re.sub(r"!\[(.*?)\]\(upload:(\d+)(?!\d)\)", _replace_image_tag, full_res_template)

            def _replace_bare_upload(m: re.Match) -> str:
                num = m.group(1)
                ref = f"upload:{num}"
                if ref in image_map:
                    return image_map[ref]
                elif ref in image_fail_map:
                    return image_fail_map[ref]
                else:
                    err_msg = "未找到对应资源"
                    image_warnings.append(f"image_import_failed:{ref}:{err_msg}")
                    return f"[图片未能导入：{err_msg}]"

            full_markdown = re.sub(r"upload:(\d+)(?!\d)", _replace_bare_upload, full_markdown)

            # Overall fidelity
            total_orig_table_cells = sum(
                len(r) for b in blocks if b.get("type") == "table" for r in b.get("rows", [])
            )
            total_orig_images = len(raw_images)
            overall_diff_ratio, overall_warnings = verify_fidelity(
                full_orig,
                full_res_template,
                orig_table_cells=total_orig_table_cells,
                orig_images_count=total_orig_images,
            )

            if segment_warnings:
                for sw in segment_warnings:
                    if sw not in overall_warnings:
                        overall_warnings.append(sw)

            if image_warnings:
                overall_warnings.extend(image_warnings)
                if "image_import_failed" not in overall_warnings:
                    overall_warnings.append("image_import_failed")

            # Title: first # heading, or filename stem
            title = ""
            m_title = re.search(r"^#\s+(.+)$", full_markdown, flags=re.MULTILINE)
            if m_title:
                title = m_title.group(1).strip()
            elif file_name:
                title = Path(file_name).stem
            else:
                title = "未命名文档"

            # AI status determination
            if ai_success_count == total_segments and total_segments > 0:
                ai_used_status = "all"
                fallback_reason = ""
            elif ai_success_count > 0:
                ai_used_status = "partial"
                fallback_reason = "partial_failure"
                if "partial_ai_fallback" not in overall_warnings:
                    overall_warnings.append("partial_ai_fallback")
            else:
                ai_used_status = "none"
                fallback_reason = "no_key" if ai_no_key_count == total_segments else "ai_failed"
                if "ai_unavailable_or_failed" not in overall_warnings:
                    overall_warnings.append("ai_unavailable_or_failed")

            result_payload = {
                "title": title,
                "markdown": full_markdown,
                "aiUsed": ai_used_status,
                "aiFailedSegments": ai_failed_segments,
                "fallbackReason": fallback_reason,
                "charDiffRatio": overall_diff_ratio,
                "warnings": overall_warnings,
                "segments": segment_results,
                "images": saved_image_urls,
                "legacyFormat": legacy_format,
            }

            # 7. Write final result in short transaction with status='running' check
            with self.db.transaction() as tx:
                cur = tx.execute(
                    """
                    UPDATE studio_import_jobs
                    SET status = 'done',
                        progress_done = ?,
                        result_json = ?,
                        error = '',
                        updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (total_segments, json.dumps(result_payload, ensure_ascii=False), utc_now_iso(), job_id),
                )
                if cur.rowcount > 0:
                    is_done = True
                else:
                    logger.warning("Job %s was aborted/timed out by watchdog; discarding result", job_id)

        finally:
            # S5: Outside of all transactions: if not done, clean up saved media
            if not is_done and saved_image_urls:
                try:
                    logger.info("Cleaning up %d media for aborted/failed job %s", len(saved_image_urls), job_id)
                    _cleanup_job_media(self.db, user_id, saved_image_urls)
                except Exception as exc:
                    logger.error("Failed to clean up job media for job %s: %s", job_id, exc)


_IMPORT_MANAGERS: dict[str, ImportManager] = {}
_IMPORT_MANAGERS_LOCK = threading.Lock()


def get_import_manager(db: Database) -> ImportManager:
    """Retrieve or create a singleton ImportManager for the given database."""
    key = str(db.db_path)
    with _IMPORT_MANAGERS_LOCK:
        mgr = _IMPORT_MANAGERS.get(key)
        if mgr is None or not getattr(mgr, "_started", False) or (getattr(mgr, "_stop", None) and mgr._stop.is_set()):
            mgr = ImportManager(db).start()
            _IMPORT_MANAGERS[key] = mgr
        return mgr
