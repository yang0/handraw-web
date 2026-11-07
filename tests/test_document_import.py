"""Tests for asynchronous chunked document imports (C2-C6, S4, S5)."""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import docx
import fitz
from PIL import Image

from backend import ai_client
from backend.db import Database, utc_now_iso
from backend.document_importer import (
    ImportManager,
    cleanup_unreferenced_import_media,
    mark_legacy_imports_failed,
    split_blocks_into_segments,
    verify_fidelity,
)
from backend.document_structure import DocumentImportError, extract_document_structure
from backend.server import create_channel_server, init_database


def _create_sample_docx() -> bytes:
    """Create a sample DOCX with 2 levels of headings, text, list, table, and 2 images."""
    doc = docx.Document()
    doc.add_heading("一级大标题：手绘风格指南", level=1)
    doc.add_paragraph("这是文章的引言段落，介绍手绘的核心设计理念与视觉规范。")

    # Add Image 1
    img1_io = io.BytesIO()
    Image.new("RGB", (20, 20), color="blue").save(img1_io, "PNG")
    img1_io.seek(0)
    doc.add_picture(img1_io)

    doc.add_heading("二级小节：基础要素", level=2)
    doc.add_paragraph("第一项基本要素：自然墨色", style="List Bullet")
    doc.add_paragraph("第二项基本要素：暖纸肌理", style="List Bullet")

    # Add Table
    tbl = doc.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "参数名称"
    tbl.cell(0, 1).text = "推荐值"
    tbl.cell(1, 0).text = "对比度"
    tbl.cell(1, 1).text = "85%"

    # Add Image 2
    img2_io = io.BytesIO()
    Image.new("RGB", (30, 30), color="green").save(img2_io, "PNG")
    img2_io.seek(0)
    doc.add_picture(img2_io)

    doc.add_paragraph("结尾总结：完成全部设计要求。")

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


def _create_sample_pdf(with_text: bool = True, pages: int = 1) -> bytes:
    """Create a sample PDF. If with_text is False, creates a scanned PDF (only images)."""
    doc = fitz.open()
    for p_idx in range(pages):
        page = doc.new_page()
        if with_text:
            page.insert_text((50, 60), "PDF 主标题", fontsize=24, fontname="helv")
            page.insert_text((50, 100), "这是正文第一段说明文字。", fontsize=11, fontname="helv")
        # Add an image
        img_io = io.BytesIO()
        Image.new("RGB", (40, 40), color="red").save(img_io, "PNG")
        page.insert_image(fitz.Rect(50, 150, 150, 250), stream=img_io.getvalue())

    return doc.tobytes()


class DocumentStructureTests(unittest.TestCase):
    def test_docx_structure_extraction(self):
        file_bytes = _create_sample_docx()
        struct = extract_document_structure(file_bytes, "sample.docx")

        blocks = struct["blocks"]
        images = struct["images"]
        self.assertFalse(struct["legacy_format"])
        self.assertEqual(len(images), 2)

        # Check block sequence
        types = [b["type"] for b in blocks]
        self.assertIn("heading", types)
        self.assertIn("paragraph", types)
        self.assertIn("list_item", types)
        self.assertIn("table", types)
        self.assertIn("image", types)

        # First block should be heading level 1
        h1 = [b for b in blocks if b["type"] == "heading" and b.get("level") == 1][0]
        self.assertEqual(h1["text"], "一级大标题：手绘风格指南")

        # Table rows check
        tbl_blocks = [b for b in blocks if b["type"] == "table"]
        self.assertEqual(len(tbl_blocks), 1)
        self.assertEqual(tbl_blocks[0]["rows"][0], ["参数名称", "推荐值"])
        self.assertEqual(tbl_blocks[0]["rows"][1], ["对比度", "85%"])

    def test_pdf_structure_and_scanned_pdf_check(self):
        # 1. Normal PDF
        pdf_bytes = _create_sample_pdf(with_text=True)
        struct = extract_document_structure(pdf_bytes, "test.pdf")
        self.assertGreaterEqual(len(struct["blocks"]), 1)
        self.assertEqual(len(struct["images"]), 1)

        # 2. Scanned PDF (no text)
        scanned_bytes = _create_sample_pdf(with_text=False)
        with self.assertRaises(DocumentImportError) as ctx:
            extract_document_structure(scanned_bytes, "scanned.pdf")
        self.assertIn("暂不支持扫描版 PDF", str(ctx.exception))

    def test_rtf_and_unsupported_formats(self):
        with self.assertRaises(DocumentImportError) as ctx:
            extract_document_structure(b"{\\rtf1\\ansi Hello}", "doc.rtf")
        self.assertIn("暂不支持该格式", str(ctx.exception))

        with self.assertRaises(DocumentImportError) as ctx:
            extract_document_structure(b"binary data", "doc.xyz")
        self.assertIn("暂不支持该格式", str(ctx.exception))

    def test_limits_exceeded(self):
        # 1. PDF > 300 pages
        doc = fitz.open()
        for _ in range(301):
            p = doc.new_page()
            p.insert_text((50, 50), "text", fontsize=11)
        huge_pdf = doc.tobytes()
        with self.assertRaises(DocumentImportError) as ctx:
            extract_document_structure(huge_pdf, "large.pdf")
        self.assertIn("300", str(ctx.exception))

        # 2. Extracted text > 200,000 characters
        huge_text = ("大" * 1000 + "\n\n") * 205
        with self.assertRaises(DocumentImportError) as ctx:
            extract_document_structure(huge_text.encode("utf-8"), "large.txt")
        self.assertIn("200,000", str(ctx.exception))

    def test_q4_docx_table_cell_image_extraction(self):
        doc = docx.Document()
        doc.add_heading("表格内图片测试", level=1)
        tbl = doc.add_table(rows=2, cols=2)
        tbl.cell(0, 0).text = "表头1"
        tbl.cell(0, 1).text = "表头2"
        tbl.cell(1, 0).text = "说明"

        # Embed an image inside cell(1, 1)
        p = tbl.cell(1, 1).paragraphs[0]
        img_io = io.BytesIO()
        Image.new("RGB", (32, 32), color="purple").save(img_io, "PNG")
        img_io.seek(0)
        p.add_run().add_picture(img_io)

        bio = io.BytesIO()
        doc.save(bio)
        docx_bytes = bio.getvalue()

        struct = extract_document_structure(docx_bytes, "tbl_with_image.docx")
        self.assertEqual(len(struct["images"]), 1)
        self.assertEqual(struct["images"][0]["ref"], "upload:1")

        # Table block should be followed by the image block
        types = [b["type"] for b in struct["blocks"]]
        tbl_idx = types.index("table")
        img_idx = types.index("image")
        self.assertEqual(img_idx, tbl_idx + 1)


class DocumentImportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.uploads_dir = Path(self.temp_dir.name) / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(os.environ, {"HANDRAW_UPLOADS_DIR": str(self.uploads_dir)})
        self.env_patch.start()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(self.db_path)
        self.db.migrate()
        from backend.services import register_user
        self.user, self.token = register_user(self.db, "import_tester", "password123")

    def tearDown(self):
        self.env_patch.stop()
        from backend.document_importer import _IMPORT_MANAGERS, _IMPORT_MANAGERS_LOCK
        with _IMPORT_MANAGERS_LOCK:
            mgr = _IMPORT_MANAGERS.pop(str(self.db_path), None)
            if mgr:
                mgr.stop()
        self.db.close()
        self.temp_dir.cleanup()

    def _run_due_media_gc(self):
        """Execute queued cleanup instead of assuming SQL commits unlink files."""
        from backend.media_gc import drain_media_gc
        with self.db.transaction() as tx:
            tx.execute("UPDATE media_gc_jobs SET next_attempt_at=0, claim_until=0")
        return drain_media_gc(self.db, limit=30)

    def test_fidelity_verification(self):
        # Verbatim case
        orig = "# 标题\n\n正文 100% 测试，包含数字 42 与公式 2 × 2 = 4。\n\n![](upload:1)"
        res = "# 标题\n\n正文 100% 测试，包含数字 42 与公式 2 × 2 = 4。\n\n![](upload:1)"
        ratio, issues = verify_fidelity(orig, res, orig_images_count=1)
        self.assertEqual(ratio, 0.0)
        self.assertEqual(issues, [])

        # Modified number
        res_bad_num = "# 标题\n\n正文 100% 测试，包含数字 99 与公式 2 × 2 = 4。\n\n![](upload:1)"
        ratio, issues = verify_fidelity(orig, res_bad_num, orig_images_count=1)
        self.assertIn("numbers_mismatch", issues)

        # Deleted sentence
        orig_long = "这是很长的一句话。" * 20
        res_short = "这是很长的一句话。" * 5
        ratio, issues = verify_fidelity(orig_long, res_short)
        self.assertGreater(ratio, 0.05)
        self.assertIn("possible_content_change", issues)

        # Modified formula
        res_bad_formula = "# 标题\n\n正文 100% 测试，包含数字 42 与公式 2 + 2 = 4。\n\n![](upload:1)"
        ratio, issues = verify_fidelity(orig, res_bad_formula, orig_images_count=1)
        self.assertIn("formulas_mismatch", issues)

    def test_import_job_processing_verbatim(self):
        manager = ImportManager(self.db, max_queue=5, num_workers=1)
        manager.start()
        try:
            docx_bytes = _create_sample_docx()

            # Mock AI chat to return verbatim markdown for each segment
            def mock_chat(messages, **kwargs):
                user_msg = messages[-1]["content"]
                return user_msg, {"ok": True, "reason": "", "elapsed_ms": 15}

            with patch("backend.ai_client.chat", side_effect=mock_chat):
                job_id = manager.submit_job(user_id=self.user["id"], file_name="sample.docx", file_bytes=docx_bytes)

                # Wait for job completion
                for _ in range(50):
                    time.sleep(0.1)
                    with self.db.transaction() as tx:
                        row = tx.execute("SELECT * FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                        if row and row["status"] in ("done", "failed"):
                            break

                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "done", f"Job failed with error: {row['error']}")
                result = json.loads(row["result_json"])

                self.assertEqual(result["title"], "一级大标题：手绘风格指南")
                self.assertEqual(result["aiUsed"], "all")
                self.assertEqual(result["aiFailedSegments"], [])
                self.assertEqual(result["charDiffRatio"], 0.0)
                self.assertEqual(result["warnings"], [])
                self.assertEqual(len(result["images"]), 2)
                for img_url in result["images"]:
                    self.assertTrue(img_url.startswith("/uploads/"))
                self.assertIn("| 参数名称 | 推荐值 |", result["markdown"])
        finally:
            manager.stop()

    def test_import_job_partial_ai_failure(self):
        manager = ImportManager(self.db, max_queue=5, num_workers=1)
        manager.start()
        try:
            docx_bytes = _create_sample_docx()

            # Mock AI chat: fails on first call, succeeds on subsequent
            call_count = 0

            def mock_chat(messages, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return "", {"ok": False, "reason": "timeout", "elapsed_ms": 100}
                return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 15}

            with patch("backend.ai_client.chat", side_effect=mock_chat):
                job_id = manager.submit_job(user_id=self.user["id"], file_name="sample.docx", file_bytes=docx_bytes)

                for _ in range(50):
                    time.sleep(0.1)
                    with self.db.transaction() as tx:
                        row = tx.execute("SELECT * FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                        if row and row["status"] in ("done", "failed"):
                            break

                self.assertEqual(row["status"], "done")
                result = json.loads(row["result_json"])
                self.assertEqual(result["aiUsed"], "partial")
                self.assertIn(0, result["aiFailedSegments"])
                self.assertEqual(result["fallbackReason"], "partial_failure")
        finally:
            manager.stop()

    def test_legacy_imports_recovery_on_restart(self):
        now = utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_import_jobs (id, user_id, status, file_name, created_at, updated_at)
                VALUES ('job-old-1', 1, 'running', 'doc1.docx', ?, ?)
                """,
                (now, now),
            )
            tx.execute(
                """
                INSERT INTO studio_import_jobs (id, user_id, status, file_name, created_at, updated_at)
                VALUES ('job-old-2', 1, 'queued', 'doc2.docx', ?, ?)
                """,
                (now, now),
            )

        # Service restarts and marks legacy imports as failed
        repaired = mark_legacy_imports_failed(self.db)
        self.assertEqual(repaired, 2)

        with self.db.transaction() as tx:
            r1 = tx.execute("SELECT status, error FROM studio_import_jobs WHERE id = 'job-old-1'").fetchone()
            r2 = tx.execute("SELECT status, error FROM studio_import_jobs WHERE id = 'job-old-2'").fetchone()

        self.assertEqual(r1["status"], "failed")
        self.assertEqual(r1["error"], "服务重启，请重新导入")
        self.assertEqual(r2["status"], "failed")
        self.assertEqual(r2["error"], "服务重启，请重新导入")

    def test_concurrency_no_db_write_lock_held_during_ai(self):
        """Verify that other threads can write to the database while AI calls are in flight."""
        manager = ImportManager(self.db, max_queue=5, num_workers=1)
        manager.start()

        ai_started = threading.Event()
        ai_continue = threading.Event()

        def slow_ai_chat(messages, **kwargs):
            ai_started.set()
            ai_continue.wait(timeout=5.0)
            return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 200}

        try:
            docx_bytes = _create_sample_docx()
            with patch("backend.ai_client.chat", side_effect=slow_ai_chat):
                job_id = manager.submit_job(user_id=self.user["id"], file_name="slow.docx", file_bytes=docx_bytes)

                # Wait until worker enters AI chat
                self.assertTrue(ai_started.wait(timeout=3.0), "AI chat was not entered")

                # Concurrently execute a write transaction from another thread
                write_success = False

                def another_writer():
                    nonlocal write_success
                    with self.db.transaction() as tx:
                        tx.execute("INSERT OR REPLACE INTO daily_usage (user_id, scope, usage_date, count) VALUES (999, 'test', '2026-10-31', 1)")
                    write_success = True

                writer_thread = threading.Thread(target=another_writer)
                writer_thread.start()
                writer_thread.join(timeout=1.5)

                self.assertTrue(write_success, "Another thread could not write to DB during AI call")

                # Release AI to finish
                ai_continue.set()

                # Wait for job completion
                for _ in range(50):
                    time.sleep(0.1)
                    with self.db.transaction() as tx:
                        row = tx.execute("SELECT status FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                        if row and row["status"] in ("done", "failed"):
                            break
                self.assertEqual(row["status"], "done")
        finally:
            ai_continue.set()
            manager.stop()

    def test_cleanup_unreferenced_media(self):
        uploads_dir = self.temp_dir.name / Path("uploads")
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = uploads_dir / "UPL-old.png"
        dummy_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        old_date = "2020-01-01T00:00:00Z"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at)
                VALUES ('UPL-old', ?, 'import', 'test', '/uploads/UPL-old.png', ?, 15, ?)
                """,
                (self.user["id"], str(dummy_file), old_date),
            )

        cleaned = cleanup_unreferenced_import_media(self.db, max_age_hours=1)
        self.assertEqual(cleaned, 1)
        self.assertTrue(dummy_file.exists(), "GC is deliberately deferred")
        self.assertEqual(self._run_due_media_gc()["deleted"], 1)
        self.assertFalse(dummy_file.exists())

    def test_q3_task_timeout_watchdog_and_worker_discard(self):
        manager = ImportManager(self.db, max_queue=5, num_workers=1)

        # 1. Watchdog timeout test:
        old_time = "2020-01-01T00:00:00Z"
        job_id = "job-timeout-test"
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_import_jobs (id, user_id, status, file_name, created_at, updated_at)
                VALUES (?, ?, 'running', 'slow.docx', ?, ?)
                """,
                (job_id, self.user["id"], old_time, old_time),
            )

        manager._check_timeouts_and_cleanup()
        with self.db.transaction() as tx:
            row = tx.execute("SELECT status, error FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error"], "处理超时")

        # 2. Worker attempting to complete a timed-out job cannot overwrite 'failed'
        # The file must be in the configured private-media namespace, so the
        # GC cannot be tricked into unlinking arbitrary paths outside uploads.
        img_url = f"/uploads/{uuid.uuid4().hex}_discarded.png"
        img_file = self.uploads_dir / img_url.removeprefix("/uploads/")
        img_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at)
                VALUES ('UPL-discarded', ?, 'import', 'test', ?, ?, 10, ?)
                """,
                (self.user["id"], img_url, str(img_file), old_time),
            )

        with self.db.transaction() as tx:
            cur = tx.execute(
                "UPDATE studio_import_jobs SET status = 'done', updated_at = ? WHERE id = ? AND status = 'running'",
                (utc_now_iso(), job_id),
            )
            self.assertEqual(cur.rowcount, 0)

        from backend.document_importer import _cleanup_job_media
        _cleanup_job_media(self.db, self.user["id"], [img_url])
        self.assertTrue(img_file.exists(), "Cleanup queues a GC job")
        self.assertEqual(self._run_due_media_gc()["deleted"], 1)
        self.assertFalse(img_file.exists())
        with self.db.transaction() as tx:
            saved_row = tx.execute("SELECT 1 FROM user_uploads WHERE id = 'UPL-discarded'").fetchone()
            self.assertIsNone(saved_row)

    def test_q5_image_conversion_and_corrupt_placeholder(self):
        # 1. GIF conversion to PNG via _convert_image_to_png_if_needed
        gif_io = io.BytesIO()
        Image.new("RGB", (20, 20), color="yellow").save(gif_io, format="GIF")
        gif_bytes = gif_io.getvalue()
        from backend.document_importer import _convert_image_to_png_if_needed
        png_bytes, mime = _convert_image_to_png_if_needed(gif_bytes, "image/gif")
        self.assertEqual(mime, "image/png")
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # 2. Corrupt image handling in document import job
        manager = ImportManager(self.db, max_queue=5, num_workers=1)
        manager.start()
        try:
            doc = docx.Document()
            doc.add_heading("损坏图片测试", level=1)
            doc.add_paragraph("正文第一段说明。")
            img_io = io.BytesIO()
            Image.new("RGB", (10, 10), color="red").save(img_io, "PNG")
            doc.add_picture(img_io)
            bio = io.BytesIO()
            doc.save(bio)
            docx_bytes = bio.getvalue()

            def mock_chat(messages, **kwargs):
                return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 10}

            real_extract = extract_document_structure
            def patched_extract(b, name):
                res = real_extract(b, name)
                res["images"][0]["bytes"] = b"not_a_valid_image_header_at_all"
                return res

            with patch("backend.document_importer.extract_document_structure", side_effect=patched_extract):
                with patch("backend.ai_client.chat", side_effect=mock_chat):
                    job_id = manager.submit_job(user_id=self.user["id"], file_name="corrupt.docx", file_bytes=docx_bytes)
                    for _ in range(50):
                        time.sleep(0.1)
                        with self.db.transaction() as tx:
                            row = tx.execute("SELECT * FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                            if row and row["status"] in ("done", "failed"):
                                break
                    self.assertEqual(row["status"], "done")
                    result = json.loads(row["result_json"])
                    self.assertIn("image_import_failed", result["warnings"])
                    self.assertIn("[图片未能导入：", result["markdown"])
                    self.assertNotIn("upload:1", result["markdown"])
        finally:
            manager.stop()

    def test_q6_fidelity_check_code_content_preservation(self):
        orig = "# 代码测试\n\n```python\ndef execute_task():\n    perform_action()\n```\n\n总结段落。"
        res_deleted_code = "# 代码测试\n\n总结段落。"
        ratio, issues = verify_fidelity(orig, res_deleted_code)
        self.assertIn("possible_content_change", issues)

    def test_q7_split_huge_blocks(self):
        from backend.document_importer import _normalize_and_split_huge_block
        # 1. Huge paragraph of 15000 chars without newlines
        huge_text = "这是一段非常长的连续句子，测试自动拆分超长文本块的功能。" * 500
        self.assertGreater(len(huge_text), 10000)
        huge_block = {"type": "paragraph", "text": huge_text}
        split_blocks = _normalize_and_split_huge_block(huge_block, max_len=4000)
        self.assertGreater(len(split_blocks), 1)
        for b in split_blocks:
            self.assertEqual(b["type"], "paragraph")
            self.assertLessEqual(len(b["text"]), 4000)
        combined_text = "".join(b["text"] for b in split_blocks)
        self.assertEqual(len(combined_text), len(huge_text))

        # 2. Huge table with 100 rows
        header = ["序号", "项目名称", "状态描述", "备注信息"]
        rows = [header] + [[str(i), f"项目-{i}", "正常运行中", "无异常备注说明"] for i in range(1, 101)]
        huge_table_block = {"type": "table", "rows": rows}
        split_tables = _normalize_and_split_huge_block(huge_table_block, max_len=1500)
        self.assertGreater(len(split_tables), 1)
        for tbl in split_tables:
            self.assertEqual(tbl["type"], "table")
            self.assertEqual(tbl["rows"][0], header)
        total_data_rows = sum(len(tbl["rows"]) - 1 for tbl in split_tables)
        self.assertEqual(total_data_rows, 100)

        # 3. Whole pipeline through split_blocks_into_segments
        segments = split_blocks_into_segments([huge_block, huge_table_block])
        for seg in segments:
            from backend.document_importer import _block_to_local_markdown
            md = "\n\n".join(_block_to_local_markdown(b) for b in seg)
            self.assertLessEqual(len(md), 6000)

    def test_q8_cleanup_unreferenced_import_media(self):
        uploads_dir = self.uploads_dir
        uploads_dir.mkdir(parents=True, exist_ok=True)

        f_old_unref = uploads_dir / "old_unref.png"
        f_old_unref.write_bytes(b"\x89PNG\r\n\x1a\nold")

        f_new_unref = uploads_dir / "new_unref.png"
        f_new_unref.write_bytes(b"\x89PNG\r\n\x1a\nnew")

        f_old_ref = uploads_dir / "old_ref.png"
        f_old_ref.write_bytes(b"\x89PNG\r\n\x1a\nref")

        old_dt = "2020-01-01T00:00:00Z"
        recent_dt = utc_now_iso()

        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at) VALUES ('UPL-old-unref', ?, 'import', 'test', '/uploads/old_unref.png', ?, 10, ?)",
                (self.user["id"], str(f_old_unref), old_dt),
            )
            tx.execute(
                "INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at) VALUES ('UPL-new-unref', ?, 'import', 'test', '/uploads/new_unref.png', ?, 10, ?)",
                (self.user["id"], str(f_new_unref), recent_dt),
            )
            tx.execute(
                "INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at) VALUES ('UPL-old-ref', ?, 'import', 'test', '/uploads/old_ref.png', ?, 10, ?)",
                (self.user["id"], str(f_old_ref), old_dt),
            )
            tx.execute(
                "INSERT INTO studio_import_jobs (id, user_id, status, result_json, file_name, created_at, updated_at) VALUES ('job-ref', ?, 'done', ?, 'ref.docx', ?, ?)",
                (self.user["id"], json.dumps({"images": ["/uploads/old_ref.png"]}), old_dt, old_dt),
            )

        cleaned = cleanup_unreferenced_import_media(self.db, max_age_hours=24)
        self.assertEqual(cleaned, 1)
        self.assertTrue(f_old_unref.exists())
        self.assertEqual(self._run_due_media_gc()["deleted"], 1)
        self.assertFalse(f_old_unref.exists())
        self.assertTrue(f_new_unref.exists())
        self.assertTrue(f_old_ref.exists())

    def test_q9_fidelity_table_cells_empty_and_escaped_pipe(self):
        orig = (
            "| 列一 | 列二 | 列三 |\n"
            "| --- | --- | --- |\n"
            "| 数据A | | 数据C含\\|转义竖线 |"
        )
        res = (
            "| 列一 | 列二 | 列三 |\n"
            "| --- | --- | --- |\n"
            "| 数据A | | 数据C含\\|转义竖线 |"
        )
        ratio, issues = verify_fidelity(orig, res, orig_table_cells=6)
        self.assertNotIn("table_cells_mismatch", issues)

    def test_s2_twelve_images_no_prefix_corruption(self):
        """S2: 12 images in docx must all map correctly without upload:10 prefix corruption."""
        manager = ImportManager(self.db, max_queue=5, num_workers=1)
        manager.start()
        try:
            doc = docx.Document()
            doc.add_heading("十二张图片测试", level=1)
            for i in range(1, 13):
                doc.add_paragraph(f"段落说明 {i}")
                img_io = io.BytesIO()
                Image.new("RGB", (10 + i, 10 + i), color="blue").save(img_io, "PNG")
                doc.add_picture(img_io)

            bio = io.BytesIO()
            doc.save(bio)
            docx_bytes = bio.getvalue()

            def mock_chat(messages, **kwargs):
                return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 10}

            with patch("backend.ai_client.chat", side_effect=mock_chat):
                job_id = manager.submit_job(user_id=self.user["id"], file_name="twelve.docx", file_bytes=docx_bytes)
                for _ in range(50):
                    time.sleep(0.1)
                    with self.db.transaction() as tx:
                        row = tx.execute("SELECT * FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                        if row and row["status"] in ("done", "failed"):
                            break

                self.assertEqual(row["status"], "done")
                result = json.loads(row["result_json"])
                self.assertEqual(len(result["images"]), 12)
                self.assertEqual(result["warnings"], [])

                md = result["markdown"]
                matches = re.findall(r"!\[.*?\]\((/uploads/[^\)]+)\)", md)
                self.assertEqual(len(matches), 12)
                for url in matches:
                    self.assertTrue(url.endswith(".png"), f"Corrupted URL: {url}")
                    self.assertFalse(url.endswith(".png0"))
                    self.assertFalse(url.endswith(".png1"))
                    self.assertFalse(url.endswith(".png2"))
                self.assertNotIn("upload:", md)
        finally:
            manager.stop()

    def test_s3_heading_too_long_converts_to_paragraph_with_warning(self):
        """S3: Super-long headings (>5000 chars) convert to paragraph and warn."""
        w: list[str] = []
        long_heading = "这是一个超级长的第一级大标题文字。" * 300
        self.assertGreater(len(long_heading), 5000)
        h_block = {"type": "heading", "level": 1, "text": long_heading}
        from backend.document_importer import _normalize_and_split_huge_block
        split_res = _normalize_and_split_huge_block(h_block, max_len=4000, warnings=w)
        self.assertIn("heading_too_long", w)
        self.assertGreater(len(split_res), 1)
        for b in split_res:
            self.assertEqual(b["type"], "paragraph")
            self.assertLessEqual(len(b["text"]), 4000)
        combined = "".join(b["text"] for b in split_res)
        self.assertEqual(len(combined), len(long_heading))

    def test_s4_table_row_or_header_too_long(self):
        """S4: Table row or header exceeding max_len is expanded to paragraphs."""
        # Case A: 9000-char cell in row
        long_cell = "长单元格内容" * 1500
        rows_a = [["表头A", "表头B"], ["1", long_cell]]
        w_a: list[str] = []
        segs_a = split_blocks_into_segments([{"type": "table", "rows": rows_a}], warnings=w_a)
        self.assertIn("table_row_too_long", w_a)
        for seg in segs_a:
            from backend.document_importer import _block_to_local_markdown
            md = "\n\n".join(_block_to_local_markdown(b) for b in seg)
            self.assertLessEqual(len(md), 6000)
        all_text_a = "".join(b.get("text", "") for seg in segs_a for b in seg)
        self.assertIn(long_cell, all_text_a)

        # Case B: 9000-char header
        long_header_cell = "超长表头" * 2250
        rows_b = [[long_header_cell, "表头2"], ["数据1", "数据2"], ["数据3", "数据4"]]
        w_b: list[str] = []
        segs_b = split_blocks_into_segments([{"type": "table", "rows": rows_b}], warnings=w_b)
        self.assertIn("table_row_too_long", w_b)
        for seg in segs_b:
            from backend.document_importer import _block_to_local_markdown
            md = "\n\n".join(_block_to_local_markdown(b) for b in seg)
            self.assertLessEqual(len(md), 6000)
        all_text_b = "".join(b.get("text", "") for seg in segs_b for b in seg)
        self.assertIn(long_header_cell, all_text_b)

    def test_s5_timeout_task_media_cleaned_up_real_worker_path(self):
        """S5: Real worker path cleans up saved media if job times out/fails."""
        manager = ImportManager(self.db, max_queue=5, num_workers=1)
        manager.start()
        try:
            doc = docx.Document()
            doc.add_heading("超时清理测试", level=1)
            doc.add_paragraph("正文测试说明")
            img_io = io.BytesIO()
            Image.new("RGB", (20, 20), color="red").save(img_io, "PNG")
            doc.add_picture(img_io)
            bio = io.BytesIO()
            doc.save(bio)
            docx_bytes = bio.getvalue()

            def slow_ai_chat(messages, **kwargs):
                time.sleep(0.3)
                return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 300}

            with patch("backend.document_importer.MAX_JOB_DURATION_SECONDS", 0.1):
                with patch("backend.ai_client.chat", side_effect=slow_ai_chat):
                    job_id = manager.submit_job(user_id=self.user["id"], file_name="timeout_media.docx", file_bytes=docx_bytes)
                    for _ in range(50):
                        time.sleep(0.1)
                        with self.db.transaction() as tx:
                            row = tx.execute("SELECT * FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                            if row and row["status"] in ("done", "failed"):
                                break

                    self.assertEqual(row["status"], "failed")
                    self.assertIn("处理超时", row["error"])

                    with self.db.transaction() as tx:
                        uploads = tx.execute("SELECT * FROM user_uploads WHERE user_id = ?", (self.user["id"],)).fetchall()
                    self.assertEqual(len(uploads), 0, f"Expected 0 uploads but found: {[u['image_url'] for u in uploads]}")
        finally:
            manager.stop()

    def test_s6_recreate_manager_after_stop_works(self):
        """S6: Stopping and recreating the import manager produces a working manager with active workers and watchdog."""
        from backend.document_importer import get_import_manager
        mgr1 = get_import_manager(self.db)
        self.assertTrue(mgr1._started)

        mgr1.stop()
        self.assertFalse(mgr1._started)

        mgr2 = get_import_manager(self.db)
        self.assertIsNot(mgr1, mgr2)
        self.assertTrue(mgr2._started)
        self.assertIsNotNone(mgr2._watchdog_thread)
        self.assertTrue(mgr2._watchdog_thread.is_alive())
        self.assertGreaterEqual(len(mgr2.workers), 1)

        def mock_chat(messages, **kwargs):
            return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 10}

        with patch("backend.ai_client.chat", side_effect=mock_chat):
            job_id = mgr2.submit_job(user_id=self.user["id"], file_name="test_mgr2.txt", file_bytes=b"hello mgr2")
            for _ in range(50):
                time.sleep(0.1)
                with self.db.transaction() as tx:
                    row = tx.execute("SELECT status FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                    if row and row["status"] in ("done", "failed"):
                        break
            self.assertEqual(row["status"], "done")

        mgr2.stop()

    def test_s8_corrupt_png_idat_produces_warning_and_no_saved_media(self):
        """S8: PNG with valid header but corrupt IDAT fails decode, warns, and saves no media."""
        corrupt_png = b"\x89PNG\r\n\x1a\n" + b"broken_corrupt_idat_data_garbage"

        from backend.document_importer import _convert_image_to_png_if_needed
        with self.assertRaises(DocumentImportError):
            _convert_image_to_png_if_needed(corrupt_png, "image/png")

        manager = ImportManager(self.db, max_queue=5, num_workers=1)
        manager.start()
        try:
            doc = docx.Document()
            doc.add_heading("损坏图片测试S8", level=1)
            doc.add_paragraph("正文第一段说明。")
            img_io = io.BytesIO()
            Image.new("RGB", (10, 10), color="blue").save(img_io, "PNG")
            doc.add_picture(img_io)
            bio = io.BytesIO()
            doc.save(bio)
            docx_bytes = bio.getvalue()

            def mock_chat(messages, **kwargs):
                return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 10}

            real_extract = extract_document_structure
            def patched_extract(b, name):
                res = real_extract(b, name)
                res["images"][0]["bytes"] = corrupt_png
                return res

            with patch("backend.document_importer.extract_document_structure", side_effect=patched_extract):
                with patch("backend.ai_client.chat", side_effect=mock_chat):
                    job_id = manager.submit_job(user_id=self.user["id"], file_name="corrupt_s8.docx", file_bytes=docx_bytes)
                    for _ in range(50):
                        time.sleep(0.1)
                        with self.db.transaction() as tx:
                            row = tx.execute("SELECT * FROM studio_import_jobs WHERE id = ?", (job_id,)).fetchone()
                            if row and row["status"] in ("done", "failed"):
                                break

                    self.assertEqual(row["status"], "done")
                    result = json.loads(row["result_json"])
                    self.assertIn("image_import_failed", result["warnings"])
                    self.assertIn("[图片未能导入：", result["markdown"])
                    self.assertNotIn("upload:1", result["markdown"])
                    self.assertEqual(len(result["images"]), 0)

                    with self.db.transaction() as tx:
                        uploads = tx.execute("SELECT * FROM user_uploads WHERE user_id = ?", (self.user["id"],)).fetchall()
                    self.assertEqual(len(uploads), 0)
        finally:
            manager.stop()

    def test_s9_long_table_split_across_segments_verbatim_no_false_cell_mismatch(self):
        """S9: Table split across segments repeating headers verbatim must not report table_cells_mismatch."""
        header = ["列一", "列二"]
        orig_cells = 2 * 101  # 202 cells

        orig_table_md = "| " + " | ".join(header) + " |\n| --- | --- |\n" + "\n".join(f"| A{i} | B{i} |" for i in range(1, 101))

        seg1_md = "| " + " | ".join(header) + " |\n| --- | --- |\n" + "\n".join(f"| A{i} | B{i} |" for i in range(1, 51))
        seg2_md = "| " + " | ".join(header) + " |\n| --- | --- |\n" + "\n".join(f"| A{i} | B{i} |" for i in range(51, 101))
        res_text = f"{seg1_md}\n\n{seg2_md}"

        ratio, issues = verify_fidelity(orig_table_md, res_text, orig_table_cells=orig_cells)
        self.assertNotIn("table_cells_mismatch", issues)


class ImportHttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_dir = Path(cls.temp_dir.name) / "uploads"
        cls.uploads_dir.mkdir(parents=True, exist_ok=True)
        cls.env_patch = patch.dict(os.environ, {"HANDRAW_UPLOADS_DIR": str(cls.uploads_dir), "HANDRAW_DEMO_MODE": "0", "HANDRAW_ALLOWED_ORIGINS": "https://studio.handraw-style.com"})
        cls.env_patch.start()
        cls.db_path = Path(cls.temp_dir.name) / "http_test.db"
        cls.db = init_database(cls.db_path)
        from backend.services import register_user
        cls.u1, cls.tok1 = register_user(cls.db, "import_user_1", "password123")
        cls.u2, cls.tok2 = register_user(cls.db, "import_user_2", "password123")
        cls.server = create_channel_server(0, "main", cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        getattr(cls.server, "import_manager").stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.db.close()
        cls.env_patch.stop()
        cls.temp_dir.cleanup()

    def _request(self, method: str, path: str, body: dict | None = None, cookie: str = "") -> tuple[int, dict]:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {
            "Host": "studio.handraw-style.com",
            "Origin": "https://studio.handraw-style.com",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie

        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {}
        return resp.status, parsed

    def _login(self, username: str) -> str:
        status, parsed = self._request("POST", "/api/auth/login", {"account": username, "password": "password123"})
        self.assertEqual(status, 200)
        return parsed.get("token") or ""

    def test_http_api_endpoints_and_limits(self):
        # 1. Anonymous POST -> 401
        status, _ = self._request("POST", "/api/studio/imports", {"text": "hello"})
        self.assertEqual(status, 401)

        # Login as user 1
        cookie = f"handraw_sid={self._login('import_user_1')}"

        # 2. Submit first job with slow AI to guarantee it is in progress
        sample_docx = _create_sample_docx()
        b64_data = base64.b64encode(sample_docx).decode("ascii")

        ai_started = threading.Event()
        ai_continue = threading.Event()

        def slow_ai(messages, **kwargs):
            ai_started.set()
            ai_continue.wait(timeout=5.0)
            return messages[-1]["content"], {"ok": True, "reason": "", "elapsed_ms": 10}

        with patch("backend.ai_client.chat", side_effect=slow_ai):
            status, resp = self._request(
                "POST",
                "/api/studio/imports",
                {"fileName": "test.docx", "fileData": b64_data},
                cookie=cookie,
            )
            self.assertEqual(status, 200, resp)
            import_id = resp.get("importId")
            self.assertTrue(import_id)

            # Wait until worker begins processing
            self.assertTrue(ai_started.wait(timeout=3.0))

            # 3. Same user submits a second job while first is running -> 429 import_in_progress
            status2, resp2 = self._request(
                "POST",
                "/api/studio/imports",
                {"fileName": "test2.docx", "fileData": b64_data},
                cookie=cookie,
            )
            self.assertEqual(status2, 429)
            self.assertEqual(resp2.get("code"), "import_in_progress")

            # Release AI to finish
            ai_continue.set()

        # 4. Another user queries the job -> 404 not_found
        cookie_user2 = f"handraw_sid={self._login('import_user_2')}"
        status_other, resp_other = self._request("GET", f"/api/studio/imports/{import_id}", cookie=cookie_user2)
        self.assertEqual(status_other, 404)
        self.assertEqual(resp_other.get("code"), "not_found")

        # 5. Wait for user 1's job to finish and GET result
        deadline = time.monotonic() + 30
        status_done, resp_done = None, {}
        while time.monotonic() < deadline:
            time.sleep(0.1)
            status_done, resp_done = self._request("GET", f"/api/studio/imports/{import_id}", cookie=cookie)
            if status_done == 200 and resp_done.get("status") in ("done", "failed"):
                break

        self.assertEqual(status_done, 200)
        self.assertEqual(resp_done["status"], "done")
        self.assertIsNotNone(resp_done.get("result"))
        self.assertEqual(resp_done["result"]["title"], "一级大标题：手绘风格指南")

        # 6. Global queue full check (simulate 20 queued tasks)
        now = utc_now_iso()
        with self.db.transaction() as tx:
            for i in range(20):
                tx.execute(
                    "INSERT INTO studio_import_jobs (id, user_id, status, file_name, created_at, updated_at) VALUES (?, 9999, 'queued', 'dummy', ?, ?)",
                    (f"q-job-{i}", now, now),
                )
        status_qfull, resp_qfull = self._request(
            "POST",
            "/api/studio/imports",
            {"fileName": "full.txt", "text": "hello"},
            cookie=cookie,
        )
        self.assertEqual(status_qfull, 429)
        self.assertEqual(resp_qfull.get("code"), "import_queue_full")

        # Clean up simulated queue
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM studio_import_jobs WHERE user_id = 9999")

        # 7. Daily usage limit check (20 per day)
        from backend.db import local_today_str
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT OR REPLACE INTO daily_usage (user_id, scope, usage_date, count) VALUES (?, 'parse', ?, 20)",
                (self.u1["id"], local_today_str()),
            )
        status_limit, resp_limit = self._request(
            "POST",
            "/api/studio/imports",
            {"fileName": "limit.txt", "text": "hello"},
            cookie=cookie,
        )
        self.assertEqual(status_limit, 429)
        self.assertEqual(resp_limit.get("code"), "rate_limited")

    def test_q1_concurrent_race_same_user_one_wins_no_duplicate_quota(self):
        from backend.services import register_user
        from backend.db import local_today_str
        user_c, tok_c = register_user(self.db, f"race_u1_{uuid.uuid4().hex[:6]}", "password123")
        cookie_c = f"handraw_sid={tok_c}"

        barrier = threading.Barrier(2)
        results: list[tuple[int, dict]] = []
        results_lock = threading.Lock()

        pause_worker = threading.Event()
        orig_process = ImportManager._process_job

        def held_process_job(mgr_self, job_id, uid, file_name, file_bytes):
            if uid == user_c["id"]:
                pause_worker.wait(timeout=15.0)
            return orig_process(mgr_self, job_id, uid, file_name, file_bytes)

        def worker_post():
            barrier.wait()
            status, resp = self._request(
                "POST",
                "/api/studio/imports",
                {"fileName": "race.txt", "text": "concurrency test payload"},
                cookie=cookie_c,
            )
            with results_lock:
                results.append((status, resp))

        try:
            with patch.object(ImportManager, "_process_job", new=held_process_job):
                t1 = threading.Thread(target=worker_post)
                t2 = threading.Thread(target=worker_post)
                t1.start()
                t2.start()
                t1.join(timeout=15)
                t2.join(timeout=15)
        finally:
            pause_worker.set()

        statuses = sorted([r[0] for r in results])
        self.assertEqual(statuses, [200, 429])

        rejected = [r[1] for r in results if r[0] == 429][0]
        self.assertEqual(rejected.get("code"), "import_in_progress")

        today = local_today_str()
        with self.db.transaction() as tx:
            row = tx.execute(
                "SELECT count FROM daily_usage WHERE user_id = ? AND scope = 'parse' AND usage_date = ?",
                (user_c["id"], today),
            ).fetchone()
            self.assertEqual(int(row["count"]), 1)

    def test_q1_concurrent_race_global_queue_full_no_500(self):
        from backend.services import register_user
        from backend.db import local_today_str
        user_a, tok_a = register_user(self.db, f"race_qfull_a_{uuid.uuid4().hex[:6]}", "password123")
        user_b, tok_b = register_user(self.db, f"race_qfull_b_{uuid.uuid4().hex[:6]}", "password123")
        cookie_a = f"handraw_sid={tok_a}"
        cookie_b = f"handraw_sid={tok_b}"

        now = utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM studio_import_jobs WHERE status = 'queued'")
            for i in range(19):
                tx.execute(
                    "INSERT INTO studio_import_jobs (id, user_id, status, file_name, created_at, updated_at) VALUES (?, 8888, 'queued', 'dummy', ?, ?)",
                    (f"q-dummy-{i}", now, now),
                )

        worker_pause = threading.Event()
        real_process = self.server.import_manager._process_job

        def paused_process(job_id, user_id, file_name, file_bytes):
            worker_pause.wait(timeout=5.0)
            return real_process(job_id, user_id, file_name, file_bytes)

        barrier = threading.Barrier(2)
        results: list[tuple[int, dict, int]] = []

        def worker_a():
            barrier.wait()
            status, resp = self._request(
                "POST",
                "/api/studio/imports",
                {"fileName": "user_a.txt", "text": "user a payload"},
                cookie=cookie_a,
            )
            results.append((status, resp, user_a["id"]))

        def worker_b():
            barrier.wait()
            status, resp = self._request(
                "POST",
                "/api/studio/imports",
                {"fileName": "user_b.txt", "text": "user b payload"},
                cookie=cookie_b,
            )
            results.append((status, resp, user_b["id"]))

        try:
            with patch.object(self.server.import_manager, "_process_job", side_effect=paused_process):
                t1 = threading.Thread(target=worker_a)
                t2 = threading.Thread(target=worker_b)
                t1.start()
                t2.start()
                t1.join(timeout=5)
                t2.join(timeout=5)
        finally:
            worker_pause.set()

        statuses = sorted([r[0] for r in results])
        self.assertEqual(statuses, [200, 429])

        rejected = [r for r in results if r[0] == 429][0]
        self.assertEqual(rejected[1].get("code"), "import_queue_full")

        today = local_today_str()
        with self.db.transaction() as tx:
            row = tx.execute(
                "SELECT count FROM daily_usage WHERE user_id = ? AND scope = 'parse' AND usage_date = ?",
                (rejected[2], today),
            ).fetchone()
            self.assertIsNone(row)

            tx.execute("DELETE FROM studio_import_jobs WHERE user_id = 8888")

    def test_v2_header_and_row_combined_over_limit_splits_with_warning(self):
        """V2: Header 3500 chars and data row 3500 chars combined exceed limit -> split into segments <= 6000, warns table_row_too_long, content preserved."""
        # Header: 2 cols of 1750 chars each = 3500 chars
        header = ["H1_" + "a" * 1747, "H2_" + "b" * 1747]
        # Data row: 2 cols of 1750 chars each = 3500 chars
        row = ["R1_" + "c" * 1747, "R2_" + "d" * 1747]
        table_block = {
            "type": "table",
            "rows": [header, row],
        }

        warnings: list[str] = []
        segments = split_blocks_into_segments([table_block], warnings=warnings)

        # 1. table_row_too_long warning recorded
        self.assertIn("table_row_too_long", warnings)

        # 2. All segments must be <= 6000 chars
        self.assertGreater(len(segments), 1)
        for seg in segments:
            seg_md = "\n\n".join(b.get("text", "") if b.get("type") == "paragraph" else str(b) for b in seg)
            self.assertLessEqual(len(seg_md), 6000)

        # 3. Content is completely preserved (not lost)
        all_text = " ".join(b.get("text", "") for seg in segments for b in seg if b.get("type") == "paragraph")
        self.assertIn("H1_", all_text)
        self.assertIn("H2_", all_text)
        self.assertIn("R1_", all_text)
        self.assertIn("R2_", all_text)
        self.assertIn("a" * 100, all_text)
        self.assertIn("c" * 100, all_text)

    def test_v4_two_separate_original_tables_same_header_no_mismatch(self):
        """V4: Original document has two separate tables with identical headers; verbatim return produces empty issues."""
        tbl1 = (
            "| 参数 | 推荐值 |\n"
            "| --- | --- |\n"
            "| 对比度 | 85% |"
        )
        tbl2 = (
            "| 参数 | 推荐值 |\n"
            "| --- | --- |\n"
            "| 亮度 | 90% |"
        )
        orig_text = f"{tbl1}\n\n这是正文第一段说明。\n\n{tbl2}"
        res_text = orig_text
        # Two tables, each table has 2 rows * 2 cols = 4 cells; total 8 cells
        orig_table_cells = 8

        diff_ratio, issues = verify_fidelity(
            orig_text,
            res_text,
            orig_table_cells=orig_table_cells,
        )
        self.assertNotIn("table_cells_mismatch", issues)
        self.assertEqual(issues, [])

        # If segment split duplicates the header a 3rd time in res_text, the extra header is excluded
        res_split = (
            f"{tbl1}\n\n这是正文第一段说明。\n\n"
            "| 参数 | 推荐值 |\n"
            "| --- | --- |\n"
            "| 对比度_续 | 85% |\n\n"
            f"{tbl2}"
        )
        orig_cells_with_split = 10
        diff, split_issues = verify_fidelity(
            orig_text,
            res_split,
            orig_table_cells=orig_cells_with_split,
        )
        self.assertNotIn("table_cells_mismatch", split_issues)


if __name__ == "__main__":
    unittest.main()
