"""Launch content is repeatable and cannot claim existing accounts or mint credits."""
import contextlib
import io
import json
import os
import tempfile
from unittest.mock import patch
from pathlib import Path
import unittest

from ops.seed_cold_start import USERS, main, records, registry, stats
from tests.postgres_support import isolated_pg_dsn


@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class ColdStartTests(unittest.TestCase):
    def setUp(self):
        from backend.postgres_db import PostgresDatabase

        dsn = self.enterContext(isolated_pg_dsn())
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {"HANDRAW_DATABASE_URL": dsn}))
        self.db = PostgresDatabase(dsn)
        self.addCleanup(self.db.close)

    def run_command(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(["--backup-dir", str(self.folder), *args]), 0)
        return [json.loads(line) for line in stdout.getvalue().splitlines()]

    def test_preview_is_read_only(self):
        [plan] = self.run_command()
        self.assertEqual(plan["create"], {"user": 12, "topic": 24, "reply": 31})
        self.assertEqual(plan["skip"], {})
        self.assertEqual(registry(self.db.get_conn()), {})
        self.assertFalse(list(self.folder.iterdir()))
        self.assertEqual(self.db.get_conn().execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_import_is_idempotent_without_financial_or_login_grants(self):
        _, result = self.run_command('--apply')
        self.assertTrue(Path(result['backup']).is_file())
        self.assertEqual(result['changed'], {'user': 12, 'topic': 24, 'reply': 31})
        self.assertEqual(self.run_command('--apply')[0]['create'], {})
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
            self.run_command('--apply')
        conn = self.db.get_conn()
        self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT display_name FROM users').fetchone()[0], 'Existing owner')
        self.assertEqual(registry(conn), {})

    def test_pause_preserves_accounts_and_can_resume_missing_reply(self):
        rows = records()
        self.run_command('--apply')
        reply = next(row for row in rows if row[0] == 'reply')
        with self.db.transaction() as tx:
            tx.execute('DELETE FROM forum_replies WHERE id=?', (reply[1],))
        self.assertEqual(self.run_command('--apply')[-1]['changed'], {'reply': 1})
        self.run_command('--pause', '--apply')
        conn = self.db.get_conn()
        self.assertEqual(conn.execute("SELECT count(*) FROM forum_topics WHERE status='published'").fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0], 12)
        self.assertEqual(conn.execute("SELECT count(*) FROM forum_replies WHERE status='hidden'").fetchone()[0], 31)
        self.assertEqual(self.run_command('--apply')[0]['create'], {})


if __name__ == '__main__':
    unittest.main()
