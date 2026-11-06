"""Account deletion must preserve SQLite foreign-key integrity after schema growth.

The admin user-management endpoint previously returned HTTP 500 when a newly
created account had growth/security records added by later migrations.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.admin_services import admin_delete_user
from backend.server import init_database
from backend.services import register_user


class AdminUserDeletionForeignKeyTests(unittest.TestCase):
    def test_deletion_clears_recent_fk_dependents_without_disabling_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"HANDRAW_DEMO_MODE": "0", "HANDRAW_PRIVATE_STORAGE": temp}):
                db = init_database(Path(temp) / "account-delete.sqlite")
                try:
                    admin, _ = register_user(db, "delete_admin", "StrongPassword123!")
                    victim, _ = register_user(db, "delete_victim", "StrongPassword456!")
                    uid = int(victim["id"])
                    now = "2026-11-07T00:00:00Z"

                    with db.transaction() as tx:
                        tx.execute("UPDATE users SET role = 'admin' WHERE id = ?", (admin["id"],))
                        tx.execute(
                            "INSERT INTO growth_events(user_id,event_name,event_day,happened_at) VALUES (?,?,?,?)",
                            (uid, "fixture_event", "2026-11-07", now),
                        )
                        tx.execute(
                            "INSERT INTO security_devices(user_id,fingerprint,label,first_seen_at,last_seen_at)"
                            " VALUES (?,?,?,?,?)",
                            (uid, "fixture_device", "Test browser", now, now),
                        )
                        tx.execute(
                            "INSERT INTO oauth_identities(provider,provider_user_id,user_id,linked_at)"
                            " VALUES ('google',?,?,?)",
                            ("fixture_external_identity", uid, now),
                        )
                        tx.execute(
                            "INSERT INTO account_erasure_requests(user_id,requested_at) VALUES (?,?)",
                            (uid, now),
                        )
                        tx.execute(
                            "INSERT INTO tip_requests(user_id,request_id,target_type,target_id,amount,created_at)"
                            " VALUES (?,?,?,?,?,?)",
                            (uid, "fixture_tip", "work", "fixture_work", 1, now),
                        )
                        tx.execute(
                            "INSERT INTO studio_import_jobs(id,user_id,status,file_name,created_at,updated_at)"
                            " VALUES (?,?,?,?,?,?)",
                            ("imp_fixture_delete", uid, "done", "test.txt", now, now),
                        )
                        tx.execute(
                            "INSERT INTO media_public_grants(id,media_url,owner_user_id,granted_by_user_id,"
                            "target_type,target_id,granted_at) VALUES (?,?,?,?,?,?,?)",
                            ("media_fixture_delete", "/generated/fixture.png", uid, uid,
                             "work", "fixture_work", now),
                        )
                        actor_id = int(admin["id"])
                        low, high = sorted((actor_id, uid))
                        dm = tx.execute(
                            "INSERT INTO dm_conversations(user_low_id,user_high_id,created_at,updated_at)"
                            " VALUES (?,?,?,?)",
                            (low, high, now, now),
                        )
                        conversation_id = int(dm.lastrowid)
                        tx.execute(
                            "INSERT INTO dm_messages(conversation_id,sender_id,body,client_message_id,created_at)"
                            " VALUES (?,?,?,?,?)",
                            (conversation_id, uid, "Hello", "fixture_message", now),
                        )
                        tx.execute(
                            "INSERT INTO dm_members(conversation_id,user_id) VALUES (?,?)",
                            (conversation_id, uid),
                        )
                        tx.execute(
                            "INSERT INTO dm_members(conversation_id,user_id) VALUES (?,?)",
                            (conversation_id, actor_id),
                        )
                        tx.execute(
                            "INSERT INTO dm_blocks(user_id,blocked_user_id,created_at)"
                            " VALUES (?,?,?)",
                            (actor_id, uid, now),
                        )
                        tx.execute(
                            "INSERT INTO dm_contact_history(sender_id,recipient_id,first_contact_date,first_contact_at)"
                            " VALUES (?,?,?,?)",
                            (uid, actor_id, "2026-11-07", now),
                        )
                        announcement = tx.execute(
                            "INSERT INTO message_broadcasts(sender_id,title,body,audience_cutoff,request_id,published_at)"
                            " VALUES (?,?,?,?,?,?)",
                            (uid, "Test announcement", "Hello", now, "fixture_broadcast", now),
                        )
                        tx.execute(
                            "INSERT INTO message_broadcast_reads(broadcast_id,user_id,read_at) VALUES (?,?,?)",
                            (int(announcement.lastrowid), actor_id, now),
                        )
                    admin_row = dict(db.get_conn().execute(
                        "SELECT * FROM users WHERE id=?", (admin["id"],)
                    ).fetchone())
                    self.assertEqual(db.get_conn().execute("PRAGMA foreign_keys").fetchone()[0], 1)

                    deleted = admin_delete_user(db, admin_row, uid, "Test cleanup")
                    self.assertTrue(deleted["ok"])
                    self.assertIsNone(db.get_conn().execute(
                        "SELECT id FROM users WHERE id=?", (uid,)
                    ).fetchone())
                    self.assertEqual(db.get_conn().execute("PRAGMA foreign_key_check").fetchall(), [])
                    self.assertIsNotNone(db.get_conn().execute(
                        "SELECT id FROM users WHERE id=?", (admin["id"],)
                    ).fetchone())
                finally:
                    db.close()


if __name__ == "__main__":
    unittest.main()
