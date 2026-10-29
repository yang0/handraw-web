"""Launch content is repeatable and cannot claim existing accounts or mint credits."""
import tempfile
from pathlib import Path
import unittest

from backend.db import Database
from ops.seed_cold_start import USERS, apply_pack, plan, records, registry, stats


class ColdStartTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'isolated.db'
        self.db = Database(self.path)
        self.db.migrate()

    def tearDown(self):
        self.db.close()
        self.folder.cleanup()

    def test_preview_is_read_only(self):
        pending, skipped = plan(self.db.get_conn(), records())
        self.assertEqual(len(pending), 67)
        self.assertEqual(dict(skipped), {})
        self.assertEqual(registry(self.db.get_conn()), {})
        self.assertFalse((self.path.parent / 'backups').exists())
        self.assertEqual(self.db.get_conn().execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_import_is_idempotent_without_financial_or_login_grants(self):
        result = apply_pack(self.path, records())
        self.assertTrue(Path(result['backup']).is_file())
        self.assertEqual(result['changed'], {'user': 12, 'topic': 24, 'reply': 31})
        self.assertEqual(apply_pack(self.path, records())['changed'], {})
        conn = self.db.get_conn()
        self.assertEqual(conn.execute('SELECT sum(balance) FROM wallets').fetchone()[0], 0)
        for table in ['ledgers', 'sessions']:
            self.assertEqual(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT count(*) FROM users WHERE role != 'user' OR api_key IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(DISTINCT password_hash) FROM users').fetchone()[0], 12)
        self.assertEqual(conn.execute('SELECT sum(views+likes+favorites) FROM forum_topics').fetchone()[0], 0)
        self.assertEqual(stats(conn)['other_users'], 0)

    def test_existing_account_collision_rolls_back(self):
        with self.db.transaction() as tx:
            tx.execute('INSERT INTO users(username,display_name,password_hash,invite_code,created_at) VALUES (?,?,?,?,?)',
                       (USERS[0]['username'], 'Existing owner', 'unrelated-hash', 'existing-code', '2026-10-01T00:00:00Z'))
        with self.assertRaises(ValueError):
            apply_pack(self.path, records())
        conn = self.db.get_conn()
        self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT display_name FROM users').fetchone()[0], 'Existing owner')
        self.assertEqual(registry(conn), {})

    def test_pause_preserves_accounts_and_can_resume_missing_reply(self):
        rows = records()
        apply_pack(self.path, rows)
        reply = next(row for row in rows if row[0] == 'reply')
        with self.db.transaction() as tx:
            tx.execute('DELETE FROM forum_replies WHERE id=?', (reply[1],))
        self.assertEqual(apply_pack(self.path, rows)['changed'], {'reply': 1})
        apply_pack(self.path, rows, pause=True)
        conn = self.db.get_conn()
        self.assertEqual(conn.execute("SELECT count(*) FROM forum_topics WHERE status='published'").fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0], 12)
        self.assertEqual(conn.execute("SELECT count(*) FROM forum_replies WHERE status='hidden'").fetchone()[0], 31)
        self.assertEqual(apply_pack(self.path, rows)['changed'], {})


if __name__ == '__main__':
    unittest.main()
