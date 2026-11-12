"""Durable private import input, recovery across processes and lease fencing."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.document_importer import ImportManager
from backend.import_jobs import cleanup_abandoned_inputs, persist_input
from backend.postgres_db import PostgresDatabase
from backend.services import register_user
from tests.postgres_support import open_isolated_postgres


class DurableImportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.dict(os.environ, {"HANDRAW_PRIVATE_STORAGE": str(self.root)})
        )
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "durable_import", "FixturePass123!")

    def wait_terminal(self, jid, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = (
                self.db.get_conn()
                .execute("SELECT * FROM studio_import_jobs WHERE id=?", (jid,))
                .fetchone()
            )
            if row["status"] in ("done", "failed"):
                return row
            time.sleep(0.02)
        self.fail("Import did not reach a terminal state")

    def test_new_process_recovers_committed_input_without_queue_hint(self):
        environment = {
            **os.environ,
            "HANDRAW_TEST_IMPORT_DSN": self.db._dsn,
            "HANDRAW_TEST_IMPORT_UID": str(self.user["id"]),
        }
        code = """
import json,os
from backend.postgres_db import PostgresDatabase
from backend.document_importer import ImportManager
db=PostgresDatabase(os.environ['HANDRAW_TEST_IMPORT_DSN'])
jid=ImportManager(db,num_workers=0).submit_job(int(os.environ['HANDRAW_TEST_IMPORT_UID']),'recovered.txt',b'# Recovered\\n\\nOriginal document')
print(json.dumps({'id':jid}))
db.close()
"""
        process = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", code],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        jid = json.loads(process.stdout)["id"]
        row = (
            self.db.get_conn()
            .execute("SELECT * FROM studio_import_jobs WHERE id=?", (jid,))
            .fetchone()
        )
        path = self.root / "import_inputs" / row["input_storage_key"]
        self.assertTrue(path.is_file())
        manager = ImportManager(self.db, num_workers=1)
        with patch(
            "backend.ai_client.chat",
            side_effect=lambda messages, **kwargs: (
                messages[-1]["content"],
                {"ok": True},
            ),
        ):
            manager.start()
            try:
                result = self.wait_terminal(jid)
                self.assertEqual(result["status"], "done", result["error"])
                self.assertIn(
                    "Original document", json.loads(result["result_json"])["markdown"]
                )
            finally:
                manager.stop()
        self.assertFalse(path.exists())

    def test_second_pool_start_preserves_live_lease_and_stop_hands_off_safely(self):
        other = PostgresDatabase(self.db._dsn)
        self.addCleanup(other.close)
        first = ImportManager(self.db, num_workers=1)
        second = ImportManager(other, num_workers=1)
        entered = threading.Event()
        release = threading.Event()
        count = 0
        lock = threading.Lock()

        def ai(messages, **kwargs):
            nonlocal count
            self.assertIsNone(
                getattr(
                    (self.db if not entered.is_set() else other)._local, "wrapper", None
                )
            )
            with lock:
                count += 1
                number = count
            if number == 1:
                entered.set()
                release.wait(timeout=10)
            return messages[-1]["content"], {"ok": True}

        with patch("backend.ai_client.chat", side_effect=ai):
            first.start()
            threads = list(first.workers)
            try:
                jid = first.submit_job(
                    self.user["id"], "handoff.txt", b"# Handoff\n\nKeep the input"
                )
                self.assertTrue(entered.wait(timeout=5))
                self.db.get_conn().execute(
                    "UPDATE studio_import_jobs SET created_at='2000-01-01T00:00:00Z' WHERE id=?",
                    (jid,),
                )
                before = (
                    self.db.get_conn()
                    .execute(
                        "SELECT status,lease_token FROM studio_import_jobs WHERE id=?",
                        (jid,),
                    )
                    .fetchone()
                )
                second.start()
                after = (
                    self.db.get_conn()
                    .execute(
                        "SELECT status,lease_token FROM studio_import_jobs WHERE id=?",
                        (jid,),
                    )
                    .fetchone()
                )
                self.assertEqual(after, before)
                first.stop(timeout=0.05)
                result = self.wait_terminal(jid)
                self.assertEqual(result["status"], "done", result["error"])
                self.assertEqual(result["claim_count"], 2)
                committed = result["result_json"], result["updated_at"]
                release.set()
                for thread in threads:
                    thread.join(timeout=3)
                current = (
                    self.db.get_conn()
                    .execute(
                        "SELECT result_json,updated_at FROM studio_import_jobs WHERE id=?",
                        (jid,),
                    )
                    .fetchone()
                )
                self.assertEqual(
                    (current["result_json"], current["updated_at"]), committed
                )
                self.assertEqual(count, 2)
            finally:
                release.set()
                first.stop()
                second.stop()

    def test_corrupt_input_fails_without_sending_content_to_ai(self):
        manager = ImportManager(self.db, num_workers=0)
        jid = manager.submit_job(self.user["id"], "bad.txt", b"original")
        row = (
            self.db.get_conn()
            .execute(
                "SELECT input_storage_key FROM studio_import_jobs WHERE id=?", (jid,)
            )
            .fetchone()
        )
        path = self.root / "import_inputs" / row["input_storage_key"]
        path.write_bytes(b"changed on disk")
        worker = ImportManager(self.db, num_workers=1)
        with patch("backend.ai_client.chat") as chat:
            worker.start()
            try:
                result = self.wait_terminal(jid)
                self.assertEqual(result["status"], "failed")
                self.assertIn("校验失败", result["error"])
            finally:
                worker.stop()
            chat.assert_not_called()
        self.assertFalse(path.exists())

    def test_orphan_cleanup_preserves_referenced_inputs_and_unrelated_files(self):
        manager = ImportManager(self.db, num_workers=0)
        jid = manager.submit_job(self.user["id"], "queued.txt", b"queued")
        row = (
            self.db.get_conn()
            .execute(
                "SELECT input_storage_key FROM studio_import_jobs WHERE id=?", (jid,)
            )
            .fetchone()
        )
        owned = self.root / "import_inputs" / row["input_storage_key"]
        orphan, _ = persist_input("imp_" + "a" * 32, b"uncommitted")
        abandoned = self.root / "import_inputs" / orphan
        unrelated = self.root / "import_inputs" / "do-not-touch.txt"
        unrelated.write_text("unrelated", encoding="utf-8")
        for path in (owned, abandoned, unrelated):
            os.utime(path, (1, 1))
        self.assertEqual(cleanup_abandoned_inputs(self.db), 1)
        self.assertTrue(owned.is_file())
        self.assertTrue(unrelated.is_file())
        self.assertFalse(abandoned.exists())
