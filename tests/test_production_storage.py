"""Storage contracts on native PostgreSQL and Redis."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import redis_rate_limit
from backend.runtime_policy import check_auth_rate_limit
from tests.postgres_support import isolated_pg_dsn


class DummyRedis:
    def __init__(self):
        self.seen = []
    def eval(self, script, numkeys, key, window, cap):
        self.seen.append((key, window, cap))
        return int(len(self.seen) <= cap)
    def ping(self):
        return True


class RedisRateLimitTests(unittest.TestCase):
    def tearDown(self):
        redis_rate_limit._connect.cache_clear()

    def test_development_without_redis_uses_original_limiter(self):
        with patch.dict(os.environ, {"HANDRAW_REDIS_URL":"", "HANDRAW_REDIS_REQUIRED":"0"}):
            self.assertIsNone(redis_rate_limit.check_limit("login", "local-user"))
            self.assertTrue(check_auth_rate_limit("login", "unique-testing-key"))

    def test_required_redis_never_falls_back_on_missing_url(self):
        with patch.dict(os.environ, {"HANDRAW_REDIS_URL":"", "HANDRAW_REDIS_REQUIRED":"1"}):
            self.assertFalse(redis_rate_limit.check_limit("login", "alice"))
            with self.assertRaises(RuntimeError):
                redis_rate_limit.ensure_ready()

    def test_client_ip_and_account_never_enter_redis_keys(self):
        client = DummyRedis()
        with patch.dict(os.environ, {
            "HANDRAW_REDIS_URL": "redis://localhost:6379/0",
            "HANDRAW_REDIS_PREFIX": "handraw:test",
            "HANDRAW_REDIS_REQUIRED": "1"
        }), patch("backend.redis_rate_limit._connect", return_value=client):
            for _ in range(9):
                allowed = redis_rate_limit.check_limit("login", "198.51.100.9|email@example.com")
            self.assertFalse(allowed)
            self.assertEqual(len(client.seen), 9)
            self.assertEqual(client.seen[0][1:], (300, 8))
            self.assertTrue(client.seen[0][0].startswith("handraw:test:rate:login:"))
            self.assertNotIn("email@example.com", client.seen[0][0])
            self.assertNotIn("198.51.100.9", client.seen[0][0])

    @unittest.skipUnless(os.environ.get("HANDRAW_REDIS_URL"), "Real Redis not configured")
    def test_real_redis_atomic_limit_across_threads(self):
        import concurrent.futures
        import secrets
        url = os.environ["HANDRAW_REDIS_URL"]
        subject = "test-" + secrets.token_hex(16)
        with patch.dict(os.environ, {"HANDRAW_REDIS_PREFIX": "handraw:ci"}):
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                allowed = list(pool.map(
                    lambda _: redis_rate_limit.check_limit("login", subject), range(12)
                ))
        self.assertEqual(allowed.count(True), 8)
        self.assertEqual(allowed.count(False), 4)
        client = redis_rate_limit._connect(url)
        import hashlib
        key = ("handraw:ci:rate:login:" +
               hashlib.sha256(("login:" + subject).encode()).hexdigest())
        self.assertGreater(client.ttl(key), 0)
        self.assertLessEqual(client.ttl(key), 300)
        client.delete(key)

    def test_redis_outage_fails_closed_when_configured(self):
        with patch.dict(os.environ, {
            "HANDRAW_REDIS_URL": "redis://localhost:6379/0",
        }), patch("backend.redis_rate_limit._connect", side_effect=OSError("outage")):
            self.assertFalse(redis_rate_limit.check_limit("login", "alice"))

@unittest.skipUnless(os.environ.get("HANDRAW_PG_STAGING_URL"), "Isolated PostgreSQL staging URL not provided")
class NativePostgresTests(unittest.TestCase):
    def setUp(self):
        from backend.postgres_db import PostgresDatabase

        self.dsn = self.enterContext(isolated_pg_dsn())
        self.db = PostgresDatabase(self.dsn)
        self.addCleanup(self.db.close)
        self.db.migrate()

    def test_bootstrap_refuses_existing_database_and_startup_is_read_only(self):
        from ops.bootstrap_postgres_v3 import bootstrap

        with patch.dict(os.environ, {"HANDRAW_ALLOW_PG_BOOTSTRAP": "YES"}):
            with self.assertRaisesRegex(RuntimeError, "Target is not empty"):
                bootstrap(dsn=self.dsn, apply=True)
        with self.db.transaction() as tx:
            tx.execute("SET TRANSACTION READ ONLY")
            self.db.migrate()

    def test_existing_v3_requires_explicit_billing_migration(self):
        import psycopg
        from backend.postgres_db import PostgresDatabase
        from ops import bootstrap_postgres_v3

        dsn = self.enterContext(isolated_pg_dsn(initialize=False))
        previous_migrations = tuple(path for path in bootstrap_postgres_v3.MIGRATIONS if not path.name.startswith("postgres_111_"))
        with patch.object(bootstrap_postgres_v3, "MIGRATIONS", previous_migrations), patch.dict(
            os.environ, {"HANDRAW_ALLOW_PG_BOOTSTRAP": "YES"},
        ):
            bootstrap_postgres_v3.bootstrap(dsn=dsn, apply=True)

        with contextlib.closing(PostgresDatabase(dsn)) as app_db:
            with self.assertRaisesRegex(RuntimeError, "postgres_111_payment_billing.sql"):
                app_db.migrate()
            migration = next(path for path in bootstrap_postgres_v3.MIGRATIONS if path.name.startswith("postgres_111_"))
            ddl = migration.read_text(encoding="utf-8")
            with psycopg.connect(dsn) as conn:
                conn.execute(ddl)
                conn.execute("""
                    INSERT INTO public.payment_webhook_events (event_key, event_name, created_at)
                    VALUES ('fixture-event', 'order_created', '')
                """)
                conn.commit()
                conn.execute(ddl)
                self.assertEqual(conn.execute(
                    "SELECT event_key FROM public.payment_webhook_events"
                ).fetchall(), [("fixture-event",)])
                self.assertEqual(conn.execute(
                    "SELECT count(*) FROM public.schema_migrations WHERE version=111"
                ).fetchone()[0], 1)
            with app_db.transaction() as tx:
                tx.execute("SET TRANSACTION READ ONLY")
                app_db.migrate()

    def test_startup_rejects_disabled_integrity_trigger(self):
        with self.db.transaction() as tx:
            tx.execute("ALTER TABLE work_media DISABLE TRIGGER v3_cover_media_delete")
            with self.assertRaisesRegex(RuntimeError, "v3_cover_media_delete"):
                self.db.migrate()

    def test_pooled_connection_timeouts_are_configured_on_connect(self):
        from backend.postgres_db import PostgresDatabase

        with contextlib.closing(PostgresDatabase(self.dsn)) as db:
            db._pool.wait()
            first = db.get_conn()._db
            self.assertEqual(first.execute("""
                SELECT current_setting('statement_timeout'), current_setting('lock_timeout'),
                       current_setting('idle_in_transaction_session_timeout')
            """).fetchone(), ("30s", "5s", "1min"))
            db.release_request_connection()
            with patch.object(first, "execute", wraps=first.execute) as execute:
                second = db.get_conn()._db
                self.assertIs(second, first)
                execute.assert_not_called()

    def test_case_insensitive_login_unique_user_and_session_foreign_key(self):
        from psycopg.errors import ForeignKeyViolation, UniqueViolation
        from backend.services import login_user, register_user

        user, _ = register_user(self.db, "legacy", "OldUsersPassword!", "legacy@example.test")
        logged_in, token = login_user(self.db, "LeGaCy", "OldUsersPassword!")
        self.assertEqual(logged_in["id"], user["id"])
        self.assertTrue(token.startswith("hws_"))
        conn = self.db.get_conn()
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user["id"],),
        ).fetchone()[0], 2)
        other, _ = register_user(self.db, "another", "OtherUsersPassword!", "another@example.test")
        with self.assertRaises(UniqueViolation):
            conn.execute("UPDATE users SET username=? WHERE id=?", ("LeGaCy", other["id"]))
        with self.assertRaises(ForeignKeyViolation):
            conn.execute("INSERT INTO sessions(token,user_id,expires_at,created_at) VALUES ('orphan', -1, 0, '')")

    def test_imported_discourse_account_boot_and_concurrent_wallet_spend(self):
        from backend.services import login_user, register_user
        from ops.import_discourse_users import main

        pg = self.db
        account, _ = register_user(
            pg, "existing_user", "ExistingPassword2026!", "existing-user@example.test", "旧用户昵称",
        )
        original_id = account["id"]
        historical_password = "OriginalForumPassword2026!"
        historical_salt = "forum-test-salt"
        historical_hash = hashlib.pbkdf2_hmac(
            "sha256", historical_password.encode(), historical_salt.encode(), 64000
        ).hex()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = Path(temp_dir) / "forum-export.json"
            input_file.write_text(json.dumps([{
                "id": 991100, "username": "forum_existing", "email": "forum-existing@example.test",
                "name": "历史创作者", "password_hash": historical_hash, "salt": historical_salt,
            }], ensure_ascii=False), encoding="utf-8")
            with patch.dict(os.environ, {"HANDRAW_DATABASE_URL": self.dsn}):
                for expected_imports in (1, 0):
                    with contextlib.redirect_stdout(io.StringIO()) as stdout:
                        self.assertEqual(main(["--input", str(input_file)]), 0)
                    self.assertEqual(json.loads(stdout.getvalue())["imported"], expected_imports)
        historical = pg.get_conn().execute(
            "SELECT id, password_hash FROM users WHERE username='forum_existing'"
        ).fetchone()
        historical_id = historical["id"]
        self.assertEqual(historical["password_hash"], historical_hash)
        user, session = login_user(pg, "existing-user@example.test", "ExistingPassword2026!")
        self.assertEqual(user["id"], original_id)
        self.assertEqual(user["display_name"], "旧用户昵称")
        self.assertTrue(session.startswith("hws_"))
        historical_user, historical_session = login_user(
            pg, "FoRuM_ExIsTiNg", historical_password
        )
        self.assertEqual(historical_user["id"], historical_id)
        self.assertEqual(historical_user["display_name"], "历史创作者")
        self.assertTrue(historical_session.startswith("hws_"))
        updated = pg.get_conn().execute(
            "SELECT password_algo,discourse_salt FROM users WHERE id=?",
            (historical_id,)
        ).fetchone()
        self.assertEqual(updated["password_algo"], "pbkdf2_sha256")
        self.assertEqual(updated["discourse_salt"], "")
        # A new user must also be able to register *after* the migration.
        newcomer, token = register_user(pg, "new_pg_user", "BrandNewPassword2026!",
                                       "new-pg-user@example.test", "新用户昵称")
        self.assertNotEqual(newcomer["id"], original_id)
        self.assertTrue(token.startswith("hws_"))
        from backend.services import build_boot_payload
        from backend.curation import _accepted_kinds_for
        boot = build_boot_payload(pg, newcomer)
        self.assertTrue(boot["loggedIn"])
        self.assertEqual(boot["user"]["reviewAccess"]["kinds"], [])
        with pg.transaction() as tx:
            tx.execute(
                """INSERT INTO catalog_assets
                   (code,kind,source_type,author_username,name,image_url,published_at_ms,created_at,updated_at)
                   VALUES('pg_review_style','style','community','NeW_Pg_UsEr','Test','',1,'now','now')"""
            )
            tx.execute(
                """INSERT INTO works
                   (id,author_username,author_name,title,prompt,published_at_ms,created_at,updated_at)
                   VALUES('pg_review_work','NeW_Pg_UsEr','Test','Test','',1,'now','now')"""
            )
            self.assertEqual(_accepted_kinds_for(tx, newcomer["username"]), {"style", "work"})
            tx.execute("CREATE TABLE cold_start_registry(kind TEXT,item_id TEXT)")
            self.assertEqual(_accepted_kinds_for(tx, newcomer["username"]), {"style", "work"})
            tx.execute("INSERT INTO cold_start_registry VALUES('user',?)", (newcomer["username"],))
            self.assertEqual(_accepted_kinds_for(tx, newcomer["username"]), set())
        # Concurrent PG transactions must not overspend a wallet or mint
        # a duplicate ledger entry. Each thread owns a pooled connection.
        from concurrent.futures import ThreadPoolExecutor
        from backend.services import apply_wallet_delta, ServiceError
        initial = int(pg.get_conn().execute(
            "SELECT balance FROM wallets WHERE user_id=?", (newcomer["id"],)
        ).fetchone()["balance"])
        def spend(i):
            try:
                with pg.transaction() as tx:
                    apply_wallet_delta(
                        tx, newcomer["id"], -1, "pg_parity_spend",
                        "PG concurrent wallet test", event_key=f"pg-parity-{i}"
                    )
                return True
            except ServiceError as exc:
                if exc.code == "insufficient_credits":
                    return False
                raise
            finally:
                pg.close_thread_conn()
        attempts = initial + 5
        with ThreadPoolExecutor(max_workers=6) as pool:
            verdicts = list(pool.map(spend, range(attempts)))
        self.assertEqual(verdicts.count(True), initial)
        self.assertEqual(verdicts.count(False), 5)
        self.assertEqual(pg.get_conn().execute(
            "SELECT balance FROM wallets WHERE user_id=?", (newcomer["id"],)
        ).fetchone()["balance"], 0)
        self.assertEqual(pg.get_conn().execute(
            "SELECT COUNT(*) FROM ledgers WHERE user_id=? AND kind='pg_parity_spend'",
            (newcomer["id"],)
        ).fetchone()[0], initial)

    def test_batch_post_and_work_details_on_postgresql(self):
        from types import SimpleNamespace
        from backend.generation_works import project_generation_to_works
        from backend.post_routes import _handle_detail
        from backend.services import register_user
        from backend.works_feed import get_work_by_id

        pg = self.db
        images = [
            "/images/individual/FA/FA-013.webp",
            "/images/individual/FA/FA-014.webp",
            "/images/individual/FA/FA-015.webp",
        ]
        author, _ = register_user(pg, "batch_order_author", "IsolatedBatchPassword!")
        with pg.transaction() as tx:
            tx.execute(
                """
                INSERT INTO studio_generations
                   (id,user_id,username,tab_title,mode,prompt,visible_prompt,
                    items_json,engine,status,created_at,visibility)
                VALUES ('pg_order_v3',?,?,?,?,?,?,?,'live','success',?,'public')
                """,
                (
                    author["id"], author["username"], "三张插画",
                    "graphic-text", "春日主题", "春日主题",
                    json.dumps([{"id": str(i), "imageUrl": image}
                                for i, image in enumerate(images)]),
                    "2026-11-07T00:00:00Z",
                ),
            )
            work_ids = project_generation_to_works(tx, "pg_order_v3")
        self.assertEqual(len(work_ids), 1)
        work_id = work_ids[0]
        # A post-detail GET must be strictly read-only.
        with pg.transaction() as tx:
            tx.execute("SET TRANSACTION READ ONLY")
            work = get_work_by_id(pg, work_id)
            self.assertEqual(work["images"], images)
            self.assertEqual(work["batchTotal"], 1)
            conn = pg.get_conn()
            topic = conn.execute(
                "SELECT id FROM forum_topics WHERE work_id=?", (work_id,),
            ).fetchone()
            self.assertIsNotNone(topic)
            replies = []
            handler = SimpleNamespace(
                db=pg,
                _current_user=lambda required=False: None,
                _send_json=replies.append,
            )
            self.assertTrue(_handle_detail(handler, topic["id"]))
            self.assertEqual(replies[-1]["mount"]["work"]["images"], images)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM work_media WHERE work_id=?", (work_id,),
            ).fetchone()[0], 3)

    def test_messaging_lifecycle_on_postgresql(self):
        from backend.services import register_user, ServiceError
        from backend.messaging import (
            send_direct_message, list_dm_messages, mark_dm_read, get_messages_unread_summary,
            block_user, unblock_user, send_message_broadcast, mark_message_broadcast_read,
            withdraw_message_broadcast,
        )

        pg = self.db
        sender, recipient, outsider = (
            register_user(pg, name, "IsolatedMessagingPassword!")[0]
            for name in ("pg_dm_sender", "pg_dm_recipient", "pg_dm_admin")
        )
        pg.get_conn().execute("UPDATE users SET role='admin' WHERE id=?", (outsider["id"],))
        outsider["role"] = "admin"
        payload = {'recipientId': recipient['id'], 'body': 'Isolated PG message', 'clientMessageId': 'pg-dm-first'}
        first = send_direct_message(pg, sender, payload)
        self.assertTrue(first['ok'])
        self.assertGreater(first['conversationId'], 0)
        self.assertGreater(first['message']['id'], 0)
        replay = send_direct_message(pg, sender, payload)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['message']['id'], first['message']['id'])
        second = send_direct_message(pg, sender, dict(payload, clientMessageId='pg-dm-second'))
        conv_id = first['conversationId']
        self.assertEqual(second['conversationId'], conv_id)
        cursor = mark_dm_read(pg, recipient, conv_id, {'messageId': second['message']['id']})
        self.assertEqual(cursor['lastReadMessageId'], second['message']['id'])
        cursor = mark_dm_read(pg, recipient, conv_id, {'messageId': first['message']['id']})
        self.assertEqual(cursor['lastReadMessageId'], second['message']['id'])
        self.assertEqual(get_messages_unread_summary(pg, recipient)['direct'], 0)
        reply = send_direct_message(pg, recipient, {'recipientId': sender['id'], 'body': 'Isolated reply', 'clientMessageId': 'pg-dm-reply'})
        self.assertEqual(reply['conversationId'], conv_id)
        self.assertEqual(get_messages_unread_summary(pg, sender)['direct'], 1)
        self.assertEqual(len(list_dm_messages(pg, sender, conv_id, {})['messages']), 3)
        with self.assertRaises(ServiceError) as denied:
            list_dm_messages(pg, outsider, conv_id, {})
        self.assertEqual(denied.exception.status, 403)
        block_user(pg, recipient, {'userId': sender['id']})
        with self.assertRaises(ServiceError) as blocked:
            send_direct_message(pg, sender, dict(payload, clientMessageId='pg-dm-blocked'))
        self.assertEqual(blocked.exception.code, 'dm_blocked')
        unblock_user(pg, recipient, str(sender['id']))
        sent = send_direct_message(pg, sender, dict(payload, clientMessageId='pg-dm-after-unblock'))
        self.assertTrue(sent['ok'])
        broadcast = send_message_broadcast(pg, outsider, {'title': 'Isolated notice', 'body': 'Isolated broadcast', 'requestId': 'pg-broadcast'})
        bc_id = broadcast['broadcast']['id']
        self.assertGreater(bc_id, 0)
        self.assertTrue(mark_message_broadcast_read(pg, sender, bc_id)['ok'])
        self.assertTrue(withdraw_message_broadcast(pg, outsider, bc_id)['ok'])
        self.assertEqual(pg.get_conn().execute('SELECT COUNT(*) FROM dm_messages').fetchone()[0], 4)
        self.assertEqual(pg.get_conn().execute('SELECT COUNT(*) FROM dm_conversations').fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
