"""PostgreSQL author visibility regression."""
import unittest
from tests.postgres_support import open_isolated_postgres
from backend import services as S
from backend.server import build_boot_payload


class AuthorVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.db = open_isolated_postgres(self)
        for name in ("alice", "bob", "carol"):
            S.register_user(self.db, name, "TestPass123!")

    def test_work_topic_is_not_dropped_from_boot(self):
        """apply_boot used to ask resolve_resource() about works, get None, and hide them."""
        db = self.db
        db.migrate()
        conn = db.get_conn()
        conn.execute(
            """INSERT INTO works (id, author_username, author_name, title, prompt, images_json,
                                  status, origin, published_at_ms, created_at, updated_at)
               VALUES ('work_x','u','U','标题','p','[]','published','generation',1000,'刚刚','刚刚')"""
        )
        conn.execute(
            """INSERT INTO forum_topics (id, category, category_label, title, author_username, author_name,
                                        summary, status, work_id, listed_at_ms, published_at_ms, created_at, updated_at)
               VALUES ('topic_x','assets','资源','标题','u','U','s','published','work_x',1500,1500,'刚刚','刚刚')"""
        )
        conn.execute(
            "INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) "
            "VALUES ('work','work_x','topic_x','submission','刚刚')"
        )
        conn.commit()

        boot = build_boot_payload(db, None)
        ids = [t["id"] for t in boot.get("topics", [])]
        assert "topic_x" in ids, "a listed work topic must survive boot assembly"
