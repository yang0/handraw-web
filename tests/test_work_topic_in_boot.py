"""A work topic must survive boot assembly and appear once listed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db import Database
from backend.server import build_boot_payload


def test_work_topic_is_not_dropped_from_boot(tmp_path):
    """apply_boot used to ask resolve_resource() about works, get None, and hide them."""
    db = Database(tmp_path / "t.db")
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
