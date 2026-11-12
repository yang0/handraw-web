"""Fork lineage and counting.

Publishing a work records lineage only.  The parent's ``forks`` counter moves
when a *real generation* succeeds — not when a client passes ``forkOf`` to the
publish endpoint, which would let anyone inflate the counter (forks weigh 3 in
the popularity formula).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.postgres_support import open_isolated_postgres
from backend import server
from backend.services import (
    complete_cloud_generation,
    prepare_cloud_generation,
    publish_user_work,
    register_user,
)

IMG = "/images/individual/FA/FA-013.webp"


class ForkLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = open_isolated_postgres(self, seed=True)
        self.a, _ = register_user(self.db, "fork_a", "password-a")
        self.b, _ = register_user(self.db, "fork_b", "password-b")
        self.c, _ = register_user(self.db, "fork_c", "password-c")

    def tearDown(self):
        self.db.get_conn().close()
        self.db.close()
        self.temp.cleanup()

    def _publish(self, user, title, **extra):
        body = {"title": title, "prompt": f"prompt for {title}", "images": [IMG], "styles": ["FA-013"]}
        body.update(extra)
        return publish_user_work(self.db, user, body)

    def _forks(self, work_id):
        return int(
            self.db.get_conn().execute("SELECT forks FROM works WHERE id = ?", (work_id,)).fetchone()["forks"]
        )

    def test_publishing_a_fork_records_lineage_but_does_not_count(self):
        parent = self._publish(self.a, "原始作品")
        child = self._publish(self.b, "复刻一", forkOf=parent["workId"])

        # Lineage is stored...
        self.assertEqual(
            self.db.get_conn().execute("SELECT forked_from_id FROM works WHERE id = ?", (child["workId"],)).fetchone()[
                "forked_from_id"
            ],
            parent["workId"],
        )
        # ...but the counter is untouched: a client cannot inflate it.
        self.assertEqual(self._forks(parent["workId"]), 0)

    def test_publishing_without_generating_cannot_inflate_forks(self):
        parent = self._publish(self.a, "不可刷作品")
        for _ in range(3):
            self._publish(self.b, "刷一次", forkOf=parent["workId"])
            self._publish(self.c, "再刷一次", forkOf=parent["workId"])
        self.assertEqual(self._forks(parent["workId"]), 0, "forkOf at publish time must never move the counter")

    def test_successful_generation_counts_the_fork_once(self):
        parent = self._publish(self.a, "被复刻的原作")
        # Anti-farming gate: a forker needs at least one published work of their
        # own, so give B one before the generation.
        self._publish(self.b, "复刻者自己的作品")
        prepared = prepare_cloud_generation(
            self.db,
            self.b,
            {"prompt": "复刻这张的风格", "forkOf": parent["workId"], "requestId": "gen-fork-1"},
        )
        self.assertIn("genId", prepared, prepared)
        gen_id = prepared["genId"]

        complete_cloud_generation(self.db, gen_id, "task-1", ["/generated/fork-1.webp"])
        self.assertEqual(self._forks(parent["workId"]), 1, "a real generation books one fork")

        # A second completion of the same generation must not double-count.
        complete_cloud_generation(self.db, gen_id, "task-1", ["/generated/fork-1.webp"])
        self.assertEqual(self._forks(parent["workId"]), 1)

    def test_brand_new_account_generation_does_not_book_a_fork(self):
        parent = self._publish(self.a, "被新手复刻")
        prepared = prepare_cloud_generation(
            self.db,
            self.b,
            {"prompt": "我是新号", "forkOf": parent["workId"], "requestId": "gen-newbie"},
        )
        complete_cloud_generation(self.db, prepared["genId"], "task-n", ["/generated/n.webp"])
        self.assertEqual(self._forks(parent["workId"]), 0, "an account with no works of its own is not reuse")

    def test_author_generating_from_own_work_does_not_count(self):
        parent = self._publish(self.a, "自己的作品")
        prepared = prepare_cloud_generation(
            self.db,
            self.a,
            {"prompt": "自己改一版", "forkOf": parent["workId"], "requestId": "gen-self-1"},
        )
        complete_cloud_generation(self.db, prepared["genId"], "task-2", ["/generated/self-1.webp"])
        self.assertEqual(self._forks(parent["workId"]), 0, "self-forks are not reuse")

    def test_generation_without_images_does_not_count(self):
        parent = self._publish(self.a, "空生成原作")
        prepared = prepare_cloud_generation(
            self.db,
            self.b,
            {"prompt": "没有出图", "forkOf": parent["workId"], "requestId": "gen-empty-1"},
        )
        complete_cloud_generation(self.db, prepared["genId"], "task-3", [])
        self.assertEqual(self._forks(parent["workId"]), 0, "no image means no reuse")

    def test_counter_matches_fact_table(self):
        parent = self._publish(self.a, "计数一致")
        for index, user in enumerate((self.b, self.c), 1):
            # Each forker needs a published work of their own (anti-farming gate).
            self._publish(user, f"复刻者作品{index}")
            prepared = prepare_cloud_generation(
                self.db,
                user,
                {"prompt": "复刻", "forkOf": parent["workId"], "requestId": f"gen-c-{index}"},
            )
            complete_cloud_generation(self.db, prepared["genId"], f"task-c-{index}", [f"/generated/c-{index}.webp"])
        fact = int(
            self.db.get_conn()
            .execute("SELECT COUNT(*) FROM work_forks WHERE work_id = ?", (parent["workId"],))
            .fetchone()[0]
        )
        self.assertEqual(self._forks(parent["workId"]), fact)
        self.assertEqual(fact, 2)

    def test_unknown_parent_does_not_create_a_dangling_edge(self):
        orphan = self._publish(self.b, "幽灵复刻", forkOf="does-not-exist")
        self.assertEqual(
            self.db.get_conn().execute("SELECT forked_from_id FROM works WHERE id = ?", (orphan["workId"],)).fetchone()[
                "forked_from_id"
            ],
            "",
        )

    def test_unpublished_parent_is_rejected(self):
        parent = self._publish(self.a, "将被下架")
        self.db.get_conn().execute("UPDATE works SET status = 'hidden' WHERE id = ?", (parent["workId"],))
        self.db.get_conn().commit()
        child = self._publish(self.b, "复刻已下架", forkOf=parent["workId"])
        self.assertEqual(
            self.db.get_conn().execute("SELECT forked_from_id FROM works WHERE id = ?", (child["workId"],)).fetchone()[
                "forked_from_id"
            ],
            "",
            "an unpublished parent must not accept new forks",
        )


if __name__ == "__main__":
    unittest.main()
