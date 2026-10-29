"""Round-3 review fixes: the holes the second review reproduced.

Each case below is a concrete exploit or inconsistency that the reviewer
demonstrated against the running service.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend import curation as C
from backend import server
from backend.security import verify_password
from backend.services import build_boot_payload, publish_user_work, register_user

IMG = "/images/individual/FA/FA-013.webp"


class ForkCounterCannotBeGamedTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "forkgame.db")
        self.author, _ = register_user(self.db, "fg_author", "password-a")
        self.parent = publish_user_work(
            self.db, self.author, {"title": "父作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _forks(self):
        return int(
            self.db.get_conn().execute(
                "SELECT forks FROM works WHERE id = ?", (self.parent["workId"],)
            ).fetchone()["forks"]
        )

    def test_publishing_with_fork_of_writes_no_fork_fact(self):
        puppets = []
        for index in range(5):
            user, _ = register_user(self.db, f"fg_puppet{index}", "password-p")
            puppets.append(user)
            publish_user_work(
                self.db,
                user,
                {
                    "title": f"傀儡作品{index}",
                    "prompt": "p",
                    "images": [IMG],
                    "styles": ["FA-013"],
                    "forkOf": self.parent["workId"],
                },
            )
        rows = int(
            self.db.get_conn().execute("SELECT COUNT(*) FROM work_forks").fetchone()[0]
        )
        self.assertEqual(rows, 0, "publishing must never write the fork fact table")
        self.assertEqual(self._forks(), 0)


class MixedSubmissionBackdoorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "mixed.db")
        self.author, _ = register_user(self.db, "mx_author", "password-a")

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    @staticmethod
    def _item(kind, **overrides):
        item = {
            "kind": kind,
            "title": "标题",
            "name": "名称",
            "images": [IMG],
            "prompt": "提示词",
            "description": "说明",
            "definition": "定义",
        }
        item.update(overrides)
        return item

    def _submit(self, items):
        return C.submit(self.db, self.author, {"title": "帖", "text": "正文", "items": items})

    def test_work_cannot_ride_along_with_a_style(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._submit([self._item("style"), self._item("work")])
        self.assertEqual(ctx.exception.code, "work_publish_moved")

    def test_catalogue_only_submission_is_still_allowed(self):
        result = self._submit([self._item("style"), self._item("layout")])
        self.assertEqual(len(result["submissions"]), 2)

    def test_styles_are_not_silently_truncated(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._submit([self._item("work", styles=["FA-013", "FB-001", "FC-001"])])
        self.assertEqual(ctx.exception.code, "too_many_styles")

    def test_price_is_not_silently_clamped(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._submit([self._item("work", price=100000)])
        self.assertEqual(ctx.exception.code, "price_out_of_range")

    def test_non_finite_price_is_rejected(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._submit([self._item("work", price=float("inf"))])
        self.assertEqual(ctx.exception.code, "invalid_price")


class PaidPromptNeverRenderedTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "ssr.db")
        self.author, _ = register_user(self.db, "ssr_author", "password-a")
        self.work = publish_user_work(
            self.db,
            self.author,
            {
                "title": "付费SSR作品",
                "prompt": "TOPSECRET-RECIPE-abcdefghijklmnopqrstuvwxyz",
                "images": [IMG],
                "styles": ["FA-013"],
                "price": 10,
            },
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def test_boot_payload_has_no_prompt(self):
        boot = build_boot_payload(self.db, None)
        work = next(w for w in boot["works"] if w["id"] == self.work["workId"])
        self.assertEqual(work["prompt"], "")

    def test_ssr_html_has_no_prompt_fragment(self):
        # Both SSR paths must omit the recipe entirely for a paid work.
        source = Path("backend/server.py").read_text(encoding="utf-8")
        self.assertNotIn('[:34]', source, "no truncation-based teaser may remain")


class VisibilityPropagationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = server.init_database(Path(self.temp.name) / "vis2.db")
        self.author, _ = register_user(self.db, "vp_author", "password-a")
        self.work = publish_user_work(
            self.db, self.author, {"title": "举报作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _topic_status(self):
        row = self.db.get_conn().execute(
            "SELECT status FROM forum_topics WHERE id = ?", (self.work["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        return row["status"]

    def test_set_work_visibility_syncs_the_topic(self):
        from backend.services import set_work_visibility

        with self.db.transaction() as tx:
            set_work_visibility(tx, self.work["workId"], "hidden", "2026-01-01T00:00:00Z")
        self.assertEqual(self._topic_status(), "hidden")

        with self.db.transaction() as tx:
            set_work_visibility(tx, self.work["workId"], "paused", "2026-01-01T00:00:00Z")
        self.assertEqual(self._topic_status(), "paused")


class StarterCredentialRotationTests(unittest.TestCase):
    def test_rotation_script_exists_and_invalidates_old_password(self):
        from ops import rotate_starter_credentials
        from backend.security import hash_password

        with TemporaryDirectory() as tmp:
            db = server.init_database(Path(tmp) / "rot.db")
            try:
                user, _ = register_user(db, "linnan", "handraw-starter-2026")
                self.assertTrue(
                    verify_password(
                        "handraw-starter-2026",
                        db.get_conn().execute("SELECT password_hash FROM users WHERE username='linnan'").fetchone()[0],
                    )
                )
                todo = rotate_starter_credentials.plan(db)
                self.assertEqual(len(todo), 1)
                rotated = rotate_starter_credentials.apply(db, todo)
                self.assertEqual(len(rotated), 1)
                stored = db.get_conn().execute(
                    "SELECT password_hash FROM users WHERE username='linnan'"
                ).fetchone()["password_hash"]
                self.assertFalse(
                    verify_password("handraw-starter-2026", stored),
                    "the shared password must stop working after rotation",
                )
                self.assertTrue(verify_password(rotated[0]["password"], stored))
            finally:
                db.close_thread_conn()
                db.get_conn().close()
                db.close()


if __name__ == "__main__":
    unittest.main()
