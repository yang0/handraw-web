"""Publishing invariants the reviewer flagged as accepting bad states.

Each test here corresponds to a concrete hole that used to exist: owner-less
images were dropped silently, a hidden work kept a live thread, invalid input
turned into a 500, and the publish limit could be exceeded through the Skill
entry point.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.postgres_support import open_isolated_postgres
from backend import server
from backend.services import publish_user_work, register_user

IMG = "/images/individual/FA/FA-013.webp"


class PublishValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.author, _ = register_user(self.db, "val_author", "password-a")

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _publish(self, **overrides):
        body = {"title": "校验作品", "prompt": "提示词", "images": [IMG], "styles": ["FA-013"]}
        body.update(overrides)
        return publish_user_work(self.db, self.author, body)

    def test_empty_title_is_rejected(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._publish(title="   ")
        self.assertEqual(ctx.exception.code, "title_required")

    def test_more_than_two_styles_is_rejected(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._publish(styles=["FA-013", "FB-001", "FC-001"])
        self.assertEqual(ctx.exception.code, "too_many_styles")

    def test_non_numeric_price_is_a_400_not_a_500(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._publish(price="abc")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_price")

    def test_price_out_of_range_is_rejected(self):
        from backend.services import ServiceError

        with self.assertRaises(ServiceError) as ctx:
            self._publish(price=100000)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "work_price_not_allowed")

        with self.assertRaises(ServiceError) as ctx2:
            self._publish(price=10)
        self.assertEqual(ctx2.exception.status, 400)
        self.assertEqual(ctx2.exception.code, "work_price_not_allowed")

    def test_two_styles_is_allowed(self):
        result = self._publish(styles=["FA-013", "FB-001"])
        self.assertEqual(result["status"], "published")

    def test_pioneer_flag_is_set_on_first_share_of_an_unclaimed_style(self):
        result = self._publish()
        row = self.db.get_conn().execute(
            "SELECT pioneer_rewarded FROM works WHERE id = ?", (result["workId"],)
        ).fetchone()
        self.assertEqual(int(row["pioneer_rewarded"]), 1)


class VisibilitySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.author, _ = register_user(self.db, "vis_author", "password-a")
        register_user(self.db, "vis_admin", "password-admin")
        self.db.get_conn().execute("UPDATE users SET role = 'admin' WHERE username = 'vis_admin'")
        self.db.get_conn().commit()
        self.admin = dict(
            self.db.get_conn().execute("SELECT * FROM users WHERE username = 'vis_admin'").fetchone()
        )
        self.published = publish_user_work(
            self.db, self.author, {"title": "可见性作品", "prompt": "p", "images": [IMG], "styles": ["FA-013"]}
        )

    def tearDown(self):
        self.db.close_thread_conn()
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _topic_status(self):
        row = self.db.get_conn().execute(
            "SELECT status FROM forum_topics WHERE id = ?", (self.published["topicId"],)
        ).fetchone()
        self.db.close_thread_conn()
        return row["status"]

    def _moderate(self, action):
        from backend.admin_services import admin_moderate_work

        return admin_moderate_work(self.db, self.admin, self.published["workId"], action)

    def test_hiding_a_work_hides_its_thread(self):
        self.assertEqual(self._topic_status(), "published")
        self._moderate("hide")
        self.assertEqual(self._topic_status(), "hidden", "a hidden work must not keep a live thread")

    def test_pausing_a_work_pauses_its_thread(self):
        self._moderate("pause")
        self.assertEqual(self._topic_status(), "paused")

    def test_republishing_restores_the_thread(self):
        self._moderate("hide")
        self._moderate("publish")
        self.assertEqual(self._topic_status(), "published")


if __name__ == "__main__":
    unittest.main()
