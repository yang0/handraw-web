"""Real PostgreSQL polling fairness, cross-worker exclusion and stale fencing."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend.db import utc_now_iso
from backend.generation_polling import polling_claims
from backend.server import GenerationReconciler
from backend.services import (
    register_user,
    complete_cloud_generation,
    refund_failed_cloud_generation,
)
from tests.postgres_support import open_isolated_postgres


class StudioSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "scheduler", "FixturePass123!")

    def seed_jobs(self, count):
        with self.db.transaction() as tx:
            for n in range(count):
                tx.execute(
                    """INSERT INTO studio_generations
                       (id,user_id,username,engine,status,created_at,request_id,prompt,visible_prompt)
                       VALUES(?,?,?,'live','queued',?,?,'drawing','drawing')""",
                    (
                        f"poll_{n:03d}",
                        self.user["id"],
                        self.user["username"],
                        utc_now_iso(),
                        f"request_{n:03d}",
                    ),
                )

    def test_more_than_fifty_jobs_are_visited_without_starvation_or_held_connections(
        self,
    ):
        self.seed_jobs(51)
        visited = []

        def gateway(path, **kwargs):
            self.assertIsNone(
                getattr(self.db._local, "wrapper", None),
                "Network waits must release the pool connection",
            )
            visited.append(path)
            return {"items": [{"status": "running"}]}

        worker = GenerationReconciler(self.db)
        with patch("backend.server.gateway_request", side_effect=gateway):
            self.assertEqual(worker.reconcile_once(), 0)
            self.assertEqual(len(visited), 50)
            worker.reconcile_once()
        self.assertEqual(len(visited), 51)
        self.assertEqual(len(set(visited)), 51)

    def test_two_workers_poll_each_due_task_once(self):
        self.seed_jobs(51)
        barrier = threading.Barrier(2)
        local = threading.local()
        visited = []
        lock = threading.Lock()

        def gateway(path, **kwargs):
            if not getattr(local, "entered", False):
                local.entered = True
                barrier.wait(timeout=10)
            with lock:
                visited.append(path)
            return {"items": [{"status": "running"}]}

        def work(_):
            try:
                return GenerationReconciler(self.db).reconcile_once()
            finally:
                self.db.close_thread_conn()

        with patch("backend.server.gateway_request", side_effect=gateway):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(work, range(2)))
        self.assertEqual(len(visited), 51)
        self.assertEqual(len(set(visited)), 51)

    def test_replaced_or_expired_claim_cannot_complete_or_refund(self):
        self.seed_jobs(1)
        with polling_claims(self.db, limit=1) as rows:
            job = next(rows)
            self.db.get_conn().execute(
                "UPDATE studio_generations SET poll_claim_token='replacement',poll_claim_until=now()+interval '1 minute' WHERE id=?",
                (job["id"],),
            )
            complete_cloud_generation(
                self.db,
                job["id"],
                "obsolete",
                ["/images/obsolete.webp"],
                poll_claim_token=job["poll_claim_token"],
            )
            refund_failed_cloud_generation(
                self.db,
                job["id"],
                "obsolete failure",
                poll_claim_token=job["poll_claim_token"],
            )
        row = (
            self.db.get_conn()
            .execute("SELECT * FROM studio_generations WHERE id='poll_000'")
            .fetchone()
        )
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["poll_claim_token"], "replacement")
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_generation_media")
            .fetchone()[0],
            0,
        )
        self.db.get_conn().execute(
            "UPDATE studio_generations SET poll_claim_until=now()-interval '1 second' WHERE id='poll_000'"
        )
        refund_failed_cloud_generation(
            self.db, "poll_000", "expired", poll_claim_token="replacement"
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT status FROM studio_generations WHERE id='poll_000'")
            .fetchone()[0],
            "queued",
        )

    def test_poll_error_uses_bounded_backoff_and_releases_claim(self):
        self.seed_jobs(1)
        with patch(
            "backend.server.gateway_request",
            side_effect=TimeoutError("unknown upstream state"),
        ):
            GenerationReconciler(self.db, interval_seconds=15).reconcile_once()
        row = (
            self.db.get_conn()
            .execute(
                "SELECT status,poll_failures,poll_claim_token,EXTRACT(EPOCH FROM next_poll_at-now()) AS delay FROM studio_generations WHERE id='poll_000'",
            )
            .fetchone()
        )
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["poll_failures"], 1)
        self.assertIsNone(row["poll_claim_token"])
        self.assertGreater(row["delay"], 25)
        self.assertLessEqual(row["delay"], 30)
