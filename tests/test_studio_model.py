"""Studio document identity, isolated sources and real concurrent writes."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import psycopg

from backend.db import utc_now_iso
from backend.generation_v3 import ensure_run
from backend.services import (
    ServiceError,
    register_user,
    sync_user_studio_articles,
    get_studio_workspace,
    complete_cloud_generation,
    refund_failed_cloud_generation,
    prepare_cloud_generation,
)
from backend.studio_articles import get_article, select_illustration_media
from backend.studio_execution import (
    attach_attempt,
    record_attempt_media,
    apply_source_input,
)
from tests.postgres_support import open_isolated_postgres


class StudioModelTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        self.user, _ = register_user(self.db, "studio_model", "FixturePass123!")
        self.card = {
            "id": "cover",
            "role": "cover",
            "title": "封面",
            "prompt": "watercolor cat",
            "ratio": "3:4",
        }

    def save(self, aid="article", cards=None, **extra):
        return sync_user_studio_articles(
            self.db,
            self.user,
            [
                {
                    "id": aid,
                    "articleTitle": "same title",
                    "markdown": "same body",
                    "cards": [self.card] if cards is None else cards,
                    **extra,
                }
            ],
        )

    def attempt(self, aid="article", gid="attempt", **body):
        with self.db.transaction() as tx:
            rid = ensure_run(
                tx,
                user_id=self.user["id"],
                source="web",
                external_run_id=body.get("batchId") or gid,
                expected_count=1,
            )
            tx.execute(
                "INSERT INTO studio_generations(id,user_id,username,engine,status,created_at,prompt,visible_prompt,batch_id) "
                "VALUES(?,?,?,'live','running',?,'watercolor cat','watercolor cat',?)",
                (
                    gid,
                    self.user["id"],
                    self.user["username"],
                    utc_now_iso(),
                    body.get("batchId") or "",
                ),
            )
            item_id = attach_attempt(
                tx,
                self.user["id"],
                rid,
                gid,
                {
                    "creationSource": "article",
                    "articleId": aid,
                    "cardId": "cover",
                    **body,
                },
            )
        return rid, item_id

    def test_same_content_new_ids_are_independent_current_documents(self):
        self.save("one")
        self.save("two")
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_articles")
            .fetchone()[0],
            2,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM article_illustrations")
            .fetchone()[0],
            2,
        )
        self.assertEqual(
            get_article(self.db, self.user, "one")["article"]["markdown"], "same body"
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_workflows")
            .fetchone()[0],
            0,
        )

    def test_concurrent_saves_accept_one_and_preserve_current_draft(self):
        self.save()
        article = get_article(self.db, self.user, "article")["article"]
        barrier = threading.Barrier(2)

        def writer(text):
            try:
                barrier.wait(timeout=10)
                result = sync_user_studio_articles(
                    self.db,
                    self.user,
                    [
                        {
                            "id": "article",
                            "markdown": text,
                            "cards": [self.card],
                            "baseWriteSeq": article["writeSeq"],
                        }
                    ],
                )
                return (200, result)
            except ServiceError as exc:
                return (exc.status, exc.code)
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(writer, ("from A", "from B")))
        self.assertEqual(sorted(status for status, _ in outcomes), [200, 409])
        row = get_article(self.db, self.user, "article")["article"]
        self.assertIn(row["markdown"], ("from A", "from B"))
        self.assertEqual(row["writeSeq"], article["writeSeq"] + 1)
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_articles")
            .fetchone()[0],
            1,
        )

    def test_changed_card_rejects_late_result_but_keeps_attempt_media(self):
        self.save()
        self.attempt()
        changed = {**self.card, "prompt": "a different drawing"}
        self.save(cards=[changed])
        with self.db.transaction() as tx:
            generation = tx.execute(
                "SELECT * FROM studio_generations WHERE id='attempt'"
            ).fetchone()
            record_attempt_media(tx, generation, ["/images/late.webp"])
        card = get_article(self.db, self.user, "article")["article"]["cards"][0]
        self.assertEqual(card["imageUrl"], "")
        self.assertEqual(card["prompt"], changed["prompt"])
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_attempt_media")
            .fetchone()[0],
            1,
        )

    def test_removed_slot_and_deleted_article_are_not_resurrected(self):
        for aid in ("removed", "deleted"):
            self.save(aid)
            self.attempt(aid, aid + "_attempt")
        self.save("removed", cards=[])
        self.db.get_conn().execute(
            "UPDATE studio_articles SET deleted_at=? WHERE id='deleted'",
            (utc_now_iso(),),
        )
        with self.db.transaction() as tx:
            for gid in ("removed_attempt", "deleted_attempt"):
                record_attempt_media(
                    tx,
                    tx.execute(
                        "SELECT * FROM studio_generations WHERE id=?", (gid,)
                    ).fetchone(),
                    ["/images/late.webp"],
                )
        self.assertEqual(
            get_article(self.db, self.user, "removed")["article"]["cards"], []
        )
        self.assertEqual(
            self.db.get_conn()
            .execute(
                "SELECT COUNT(*) FROM article_illustrations WHERE selected_media_id IS NOT NULL"
            )
            .fetchone()[0],
            0,
        )

    def test_only_latest_attempt_selects_media(self):
        self.save()
        self.attempt(gid="first")
        self.attempt(gid="second")
        with self.db.transaction() as tx:
            record_attempt_media(
                tx,
                tx.execute(
                    "SELECT * FROM studio_generations WHERE id='second'"
                ).fetchone(),
                ["/images/current.webp"],
            )
            record_attempt_media(
                tx,
                tx.execute(
                    "SELECT * FROM studio_generations WHERE id='first'"
                ).fetchone(),
                ["/images/old.webp"],
            )
        self.assertEqual(
            get_article(self.db, self.user, "article")["article"]["cards"][0][
                "imageUrl"
            ],
            "/images/current.webp",
        )

    def test_cross_owner_and_mixed_sources_fail_atomically(self):
        self.save()
        other, _ = register_user(self.db, "other_studio", "FixturePass123!")
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.db.transaction() as tx:
                tx.execute(
                    "INSERT INTO generation_runs(id,user_id,source,external_run_id,expected_count,created_at,updated_at,creation_mode,article_id) "
                    "VALUES('bad',?,'web','bad',1,'','','article','article')",
                    (other["id"],),
                )
        with self.assertRaises(ServiceError):
            self.attempt(canvasId="canvas")
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM studio_generations")
            .fetchone()[0],
            0,
        )

    def test_manual_selection_fences_late_result_and_keeps_attempt_receipt(self):
        self.save(cards=[{**self.card, "imageUrl": "/images/original.webp"}])
        self.attempt()
        slot = get_article(self.db, self.user, "article")["article"]["cards"][0]
        chosen = select_illustration_media(
            self.db,
            self.user,
            "article",
            "cover",
            {"baseResultEpoch": slot["resultEpoch"], "imageUrl": "/images/manual.webp"},
        )
        with self.db.transaction() as tx:
            record_attempt_media(
                tx,
                tx.execute(
                    "SELECT * FROM studio_generations WHERE id='attempt'"
                ).fetchone(),
                ["/images/late.webp"],
            )
        current = get_article(self.db, self.user, "article")["article"]["cards"][0]
        self.assertEqual(current["imageUrl"], "/images/manual.webp")
        self.assertEqual(current["resultEpoch"], chosen["resultEpoch"])
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_attempt_media")
            .fetchone()[0],
            1,
        )
        with self.assertRaises(ServiceError):
            select_illustration_media(
                self.db,
                self.user,
                "article",
                "cover",
                {"baseResultEpoch": slot["resultEpoch"], "mediaId": None},
            )

    def test_changed_then_restored_spec_and_defaults_invalidate_old_results(self):
        self.save(style1="FA-001")
        self.attempt()
        self.save(cards=[{**self.card, "prompt": "temporary"}], style1="FA-001")
        self.save(style1="FA-001")
        with self.db.transaction() as tx:
            record_attempt_media(
                tx,
                tx.execute(
                    "SELECT * FROM studio_generations WHERE id='attempt'"
                ).fetchone(),
                ["/images/obsolete.webp"],
            )
        self.assertEqual(
            get_article(self.db, self.user, "article")["article"]["cards"][0][
                "imageUrl"
            ],
            "",
        )
        self.attempt(gid="defaults")
        self.save(style1="FA-002")
        with self.db.transaction() as tx:
            record_attempt_media(
                tx,
                tx.execute(
                    "SELECT * FROM studio_generations WHERE id='defaults'"
                ).fetchone(),
                ["/images/old-style.webp"],
            )
        self.assertEqual(
            get_article(self.db, self.user, "article")["article"]["cards"][0][
                "imageUrl"
            ],
            "",
        )

    def test_autosave_does_not_write_runtime_state_and_settings_advance_sequence(self):
        self.save()
        current = get_article(self.db, self.user, "article")["article"]
        self.save(
            cards=[
                {
                    **self.card,
                    "status": "generating",
                    "imageUrl": "/images/stale.webp",
                    "resultEpoch": 99,
                }
            ],
            baseWriteSeq=current["writeSeq"],
        )
        after = get_article(self.db, self.user, "article")["article"]
        self.assertEqual(after["writeSeq"], current["writeSeq"])
        self.assertEqual(after["cards"][0]["imageUrl"], "")
        self.save(settings={"coverRatio": "16:9"}, baseWriteSeq=after["writeSeq"])
        self.assertEqual(
            get_article(self.db, self.user, "article")["article"]["writeSeq"],
            after["writeSeq"] + 1,
        )

    def test_article_execution_resolves_saved_input_and_rejects_unsaved_overrides(self):
        self.save()
        body = {"creationSource": "article", "articleId": "article", "cardId": "cover"}
        apply_source_input(self.db, self.user, body)
        self.assertEqual(body["prompt"], self.card["prompt"])
        with self.assertRaises(ServiceError):
            apply_source_input(
                self.db, self.user, {**body, "prompt": "unsaved changes"}
            )
        self.save(cards=[{**self.card, "prompt": "changed"}])
        with self.assertRaises(ServiceError):
            self.attempt(**body)

    def test_projection_keeps_task_identity_and_one_task_for_multiple_media(self):
        self.save()
        rid, iid = self.attempt()
        before = (
            self.db.get_conn()
            .execute("SELECT * FROM generation_items WHERE id=?", (iid,))
            .fetchone()
        )
        complete_cloud_generation(
            self.db, "attempt", "upstream", ["/images/one.webp", "/images/two.webp"]
        )
        after = (
            self.db.get_conn()
            .execute("SELECT * FROM generation_items WHERE id=?", (iid,))
            .fetchone()
        )
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["illustration_id"], before["illustration_id"])
        self.assertEqual(after["spec_json"], before["spec_json"])
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_items WHERE run_id=?", (rid,))
            .fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM generation_attempt_media")
            .fetchone()[0],
            2,
        )
        self.assertEqual(
            self.db.get_conn().execute("SELECT COUNT(*) FROM work_media").fetchone()[0],
            2,
        )
        history = get_studio_workspace(self.db, self.user)["history"]
        run = next(entry for entry in history if entry.get("runId") == rid)
        self.assertEqual(run["imageCount"], 2)
        self.assertEqual(len(run["outputSlots"]), 1)
        complete_cloud_generation(
            self.db, "attempt", "conflicting-replay", ["/images/other.webp"]
        )
        self.assertEqual(
            get_article(self.db, self.user, "article")["article"]["cards"][0][
                "imageUrl"
            ],
            "/images/one.webp",
        )

    def test_old_attempt_refund_cannot_fail_current_retry(self):
        self.save()
        rid, iid = self.attempt(gid="old", batchId="retry")
        self.attempt(gid="new", batchId="retry")
        refund_failed_cloud_generation(self.db, "old", "old failure")
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT status FROM generation_items WHERE id=?", (iid,))
            .fetchone()[0],
            "generating",
        )
        complete_cloud_generation(self.db, "new", "new-task", ["/images/new.webp"])
        self.assertEqual(
            self.db.get_conn()
            .execute("SELECT status FROM generation_runs WHERE id=?", (rid,))
            .fetchone()[0],
            "success",
        )

    def test_concurrent_refund_releases_free_quota_once(self):
        result = prepare_cloud_generation(
            self.db,
            self.user,
            {
                "prompt": "watercolor cat",
                "promptFromSkill": True,
                "requestId": "quota-race",
            },
        )
        gid = result["genId"]
        used = (
            self.db.get_conn()
            .execute(
                "SELECT free_quota_used FROM wallets WHERE user_id=?",
                (self.user["id"],),
            )
            .fetchone()[0]
        )
        barrier = threading.Barrier(2)

        def refund(_):
            try:
                barrier.wait(timeout=10)
                refund_failed_cloud_generation(self.db, gid, "definite failure")
            finally:
                self.db.close_thread_conn()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(refund, range(2)))
        remaining = (
            self.db.get_conn()
            .execute(
                "SELECT free_quota_used FROM wallets WHERE user_id=?",
                (self.user["id"],),
            )
            .fetchone()[0]
        )
        self.assertEqual(remaining, used - 1)
