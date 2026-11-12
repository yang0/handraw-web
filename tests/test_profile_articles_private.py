"""The article list belongs to its author and to nobody else."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.legacy_database import Database
from backend import services as S


def _db(tmp_path):
    db = Database(tmp_path / "t.db")
    db.migrate()
    return db


def test_list_returns_only_the_callers_own_articles(tmp_path):
    db = _db(tmp_path)
    alice = {"id": 1, "username": "alice", "role": "user"}
    bob = {"id": 2, "username": "bob", "role": "user"}
    S.sync_user_studio_articles(db, alice, [{"id": "art_alice", "articleTitle": "爱丽丝的文章"}])
    S.sync_user_studio_articles(db, bob, [{"id": "art_bob", "articleTitle": "鲍勃的文章"}])

    a = S.list_user_studio_articles(db, alice)
    b = S.list_user_studio_articles(db, bob)

    assert [i["id"] for i in a["items"]] == ["art_alice"]
    assert [i["id"] for i in b["items"]] == ["art_bob"]


def test_a_user_without_articles_gets_an_empty_list(tmp_path):
    db = _db(tmp_path)
    out = S.list_user_studio_articles(db, {"id": 3, "username": "carol", "role": "user"})
    assert out["items"] == [] and out["total"] == 0


def test_another_users_article_id_is_not_reachable(tmp_path):
    db = _db(tmp_path)
    alice = {"id": 1, "username": "alice", "role": "user"}
    bob = {"id": 2, "username": "bob", "role": "user"}
    S.sync_user_studio_articles(db, alice, [{"id": "art_secret", "articleTitle": "机密"}])

    ids = [i["id"] for i in S.list_user_studio_articles(db, bob)["items"]]
    assert "art_secret" not in ids
