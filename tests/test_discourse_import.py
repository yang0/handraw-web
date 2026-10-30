"""Tests for Discourse user migration importer:
1. Discourse PBKDF2 hash login + transparent upgrade to pbkdf2_sha256
2. Accounts without hash/password require reset (password_reset_required)
3. Records without email skipped (skippedNoEmail)
4. Invalid usernames skipped (invalidUsernames)
5. Name/email conflicts recorded (conflicts)
6. Discourse admin/moderator imported as 'user' and listed in staffCandidates
7. Idempotent re-import (imported = 0)
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.server import init_database
from backend.services import (
    ServiceError,
    import_discourse_users_batch,
    login_user,
    register_user,
)


class DiscourseImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "disc_test.db"
        self.db = init_database(self.db_path)

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db.close()
        self.temp_dir.cleanup()

    def test_discourse_pbkdf2_hash_login_and_upgrade(self):
        # 1. 一条带 Discourse PBKDF2 哈希的记录导入后，用正确密码能登录，并且登录后 password_algo 升级为 pbkdf2_sha256；错误密码不能登录
        password = "my_secret_discourse_password"
        salt = "disc_salt_abcdef1234567890"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 64000, dklen=32)
        disc_hash = dk.hex()

        rec = {
            "username": "migrated_user",
            "email": "migrated@example.com",
            "password_hash": disc_hash,
            "salt": salt,
        }
        res = import_discourse_users_batch(self.db, None, [rec])
        self.assertEqual(res["imported"], 1)

        # 检查初始算法
        row = self.db.get_conn().execute(
            "SELECT password_algo, discourse_salt FROM users WHERE username = 'migrated_user'"
        ).fetchone()
        self.assertEqual(row["password_algo"], "discourse_pbkdf2")
        self.assertEqual(row["discourse_salt"], salt)

        # 错误密码不能登录
        with self.assertRaises(ServiceError) as ctx:
            login_user(self.db, "migrated_user", "wrong_password")
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(ctx.exception.code, "invalid_credentials")

        # 正确密码能够成功登录
        user_row, token = login_user(self.db, "migrated_user", password)
        self.assertEqual(user_row["username"], "migrated_user")
        self.assertTrue(token)

        # 登录后透明升级为 pbkdf2_sha256
        upgraded = self.db.get_conn().execute(
            "SELECT password_algo, password_hash, discourse_salt FROM users WHERE username = 'migrated_user'"
        ).fetchone()
        self.assertEqual(upgraded["password_algo"], "pbkdf2_sha256")
        self.assertTrue(upgraded["password_hash"].startswith("pbkdf2_sha256$"))
        self.assertEqual(upgraded["discourse_salt"], "")

    def test_record_without_hash_or_password_requires_reset(self):
        # 2. 没有哈希也没有明文密码的记录：导入后用 handraw123 和空密码都不能登录，登录返回 password_reset_required
        rec = {
            "username": "legacy_nohash_user",
            "email": "legacy@example.com",
        }
        res = import_discourse_users_batch(self.db, None, [rec])
        self.assertEqual(res["imported"], 1)

        # 检查 password_algo 设为 reset_required, password_hash 为空
        row = self.db.get_conn().execute(
            "SELECT password_algo, password_hash FROM users WHERE username = 'legacy_nohash_user'"
        ).fetchone()
        self.assertEqual(row["password_algo"], "reset_required")
        self.assertEqual(row["password_hash"], "")

        # 用 "handraw123" 不能登录，返回 password_reset_required (401)
        with self.assertRaises(ServiceError) as ctx1:
            login_user(self.db, "legacy_nohash_user", "handraw123")
        self.assertEqual(ctx1.exception.status, 401)
        self.assertEqual(ctx1.exception.code, "password_reset_required")
        self.assertIn("这是老论坛迁移的账号", ctx1.exception.message)

        # 用任意非空密码也不能登录，同样返回 password_reset_required (401)
        with self.assertRaises(ServiceError) as ctx2:
            login_user(self.db, "legacy_nohash_user", "any_other_pass")
        self.assertEqual(ctx2.exception.status, 401)
        self.assertEqual(ctx2.exception.code, "password_reset_required")

        # 迁移账号用空密码登录返回 400
        with self.assertRaises(ServiceError) as ctx_empty:
            login_user(self.db, "legacy_nohash_user", "")
        self.assertEqual(ctx_empty.exception.status, 400)

        # 不存在的账号用空密码登录返回 400
        with self.assertRaises(ServiceError) as ctx_nonexistent_empty:
            login_user(self.db, "non_existent_account", "")
        self.assertEqual(ctx_nonexistent_empty.exception.status, 400)

        # 断言两者状态码、错误码完全一致，杜绝利用空密码枚举账号
        self.assertEqual(ctx_empty.exception.status, ctx_nonexistent_empty.exception.status)
        self.assertEqual(ctx_empty.exception.code, ctx_nonexistent_empty.exception.code)
        self.assertEqual(ctx_empty.exception.message, ctx_nonexistent_empty.exception.message)

    def test_record_without_email_skipped(self):
        # 3. 没有邮箱的记录被跳过并出现在 skippedNoEmail
        rec = {
            "username": "user_without_email",
        }
        res = import_discourse_users_batch(self.db, None, [rec])
        self.assertEqual(res["imported"], 0)
        self.assertEqual(res["skipped"], 1)
        self.assertIn("user_without_email", res["skippedNoEmail"])

        # 数据库中不应存在该用户
        exists = self.db.get_conn().execute(
            "SELECT 1 FROM users WHERE username = 'user_without_email'"
        ).fetchone()
        self.assertIsNone(exists)

    def test_invalid_username_skipped(self):
        # 4. 用户名 li.ming 被跳过并出现在 invalidUsernames
        rec = {
            "username": "li.ming",
            "email": "liming@example.com",
        }
        res = import_discourse_users_batch(self.db, None, [rec])
        self.assertEqual(res["imported"], 0)
        self.assertEqual(res["skipped"], 1)
        self.assertIn("li.ming", res["invalidUsernames"])

        # 数据库中不应存在 li.ming 或 liming
        exists = self.db.get_conn().execute(
            "SELECT 1 FROM users WHERE username IN ('li.ming', 'liming')"
        ).fetchone()
        self.assertIsNone(exists)

    def test_conflicts_detected(self):
        # 5. 与已有账号同名或同邮箱的记录出现在 conflicts
        register_user(self.db, "existing_user", "password123")
        # Update user's email to a known value
        self.db.get_conn().execute(
            "UPDATE users SET email = 'existing_email@example.com' WHERE username = 'existing_user'"
        )

        rec_name_conflict = {
            "username": "existing_user",
            "email": "different_email@example.com",
        }
        rec_email_conflict = {
            "username": "new_username",
            "email": "existing_email@example.com",
        }

        res = import_discourse_users_batch(self.db, None, [rec_name_conflict, rec_email_conflict])
        self.assertEqual(res["imported"], 0)
        self.assertEqual(res["skipped"], 2)
        self.assertEqual(len(res["conflicts"]), 2)

        conflicts_by_user = {c["username"]: c for c in res["conflicts"]}
        self.assertIn("existing_user", conflicts_by_user)
        self.assertEqual(conflicts_by_user["existing_user"]["hit"], "username")

        self.assertIn("new_username", conflicts_by_user)
        self.assertEqual(conflicts_by_user["new_username"]["hit"], "email")

    def test_admin_imported_as_user_and_candidate(self):
        # 6. admin: true 的记录导入为 user，出现在 staffCandidates
        rec = {
            "username": "discourse_boss",
            "email": "boss@example.com",
            "admin": True,
        }
        res = import_discourse_users_batch(self.db, None, [rec])
        self.assertEqual(res["imported"], 1)
        self.assertIn("discourse_boss", res["staffCandidates"])

        row = self.db.get_conn().execute(
            "SELECT role FROM users WHERE username = 'discourse_boss'"
        ).fetchone()
        self.assertEqual(row["role"], "user")

    def test_idempotent_reimport(self):
        # 7. 同一批重复导入第二次，imported 为 0
        records = [
            {"username": "batch_u1", "email": "batch1@example.com"},
            {"username": "batch_u2", "email": "batch2@example.com"},
        ]
        res1 = import_discourse_users_batch(self.db, None, records)
        self.assertEqual(res1["imported"], 2)
        self.assertEqual(res1["skipped"], 0)

        res2 = import_discourse_users_batch(self.db, None, records)
        self.assertEqual(res2["imported"], 0)
        self.assertEqual(res2["skipped"], 2)
        self.assertEqual(len(res2["conflicts"]), 2)


if __name__ == "__main__":
    unittest.main()
