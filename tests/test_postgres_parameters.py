"""Real PostgreSQL checks for the application's qmark parameter contract."""
import unittest
from tests.postgres_support import open_isolated_postgres
from backend.user_library import is_media_referenced
from backend.services import register_user


class PostgresParameterTests(unittest.TestCase):
    def test_percent_literals_comments_and_modulo_with_parameters(self):
        db = open_isolated_postgres(self)
        conn = db.get_conn()
        row = conn.execute(
            "SELECT ? AS value, 'hist_one' LIKE 'hist_%' AS matched, "
            "7 % 3 AS remainder, '?' AS question /* 50% ? */ -- 100% ?\n",
            (42,),
        ).fetchone()
        self.assertEqual(tuple(row.values()), (42, True, 1, "?"))
        self.assertEqual(conn.execute("SELECT '100%' AS literal").fetchone()[0], "100%")
        conn.execute("CREATE TEMP TABLE params_fixture (value text)")
        conn.executemany("INSERT INTO params_fixture VALUES (? || ' 100%')", [("a",), ("b",)])
        self.assertEqual([r[0] for r in conn.execute("SELECT value FROM params_fixture ORDER BY value")],
                         ["a 100%", "b 100%"])

    def test_media_reference_with_null_and_explicit_exclusion(self):
        db = open_isolated_postgres(self)
        conn = db.get_conn()
        self.assertFalse(is_media_referenced(conn, "/uploads/orphan.png", "/tmp/orphan.png"))
        user, _ = register_user(db, "media_parameter", "TestPass123!")
        conn.execute(
            "INSERT INTO user_uploads (id,user_id,cat,name_zh,image_url,file_path,bytes,created_at) "
            "VALUES ('upl',?,'import','name','/uploads/orphan.png','/tmp/orphan.png',1,'')", (user["id"],))
        self.assertTrue(is_media_referenced(conn, "/uploads/orphan.png", "/tmp/orphan.png"))
        self.assertFalse(is_media_referenced(conn, "/uploads/orphan.png", "/tmp/orphan.png",
                                            exclude_upload_id="upl"))
