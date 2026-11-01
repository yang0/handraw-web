"""Tests for Phase 3b-10: Square cover image and single item submissions."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

from backend.server import init_database
from backend import curation as C, services as S
from backend.media_dims import image_size, is_square


class CoverImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "HANDRAW_DEMO_MODE": "0",
            "HANDRAW_PRIVATE_STORAGE": self.tmp.name,
            "HANDRAW_ALLOWED_ORIGINS": "http://trusted.test",
        })
        self.env.start()
        self.db = init_database(Path(self.tmp.name) / "test.db")
        self.uploads_dir = Path(self.tmp.name) / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        self.users = {}
        self.tokens = {}
        for name in ("author", "admin_user", "outsider"):
            u, tok = S.register_user(self.db, name, "password123")
            self.users[name] = u
            self.tokens[name] = tok

        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role='admin' WHERE username='admin_user'")
        self.admin = dict(self.users["admin_user"], role="admin")
        self.author = self.users["author"]

        C.grant_access(self.db, self.admin, {
            "usernames": ["admin_user"],
            "kinds": ["style", "layout", "work"],
            "action": "grant",
            "reason": "Test setup",
        })

    def tearDown(self):
        self.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def _create_img(self, name: str, w: int, h: int) -> str:
        fpath = self.uploads_dir / name
        img = Image.new("RGB", (w, h), color=(200, 200, 200))
        img.save(fpath)
        url = f"/uploads/{name}"
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO user_uploads (id, user_id, cat, name_zh, image_url, file_path, bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"up_{name}", self.author["id"], "other", name, url, str(fpath), 100, C._now(), C._now()),
            )
        return url

    def test_01_is_square_tolerance_rule(self):
        self.assertTrue(is_square(1000, 1006))
        self.assertTrue(is_square(1006, 1000))
        self.assertTrue(is_square(800, 800))
        self.assertTrue(is_square(50, 52))
        self.assertFalse(is_square(1200, 900))
        self.assertFalse(is_square(900, 1200))
        self.assertFalse(is_square(0, 0))

    def test_02_image_size_local_and_security(self):
        sq_url = self._create_img("sq.jpg", 400, 400)
        self.assertEqual(image_size(sq_url), (400, 400))
        self.assertIsNone(image_size("https://example.com/test.jpg"))
        self.assertIsNone(image_size("/images/FA-001.webp"))
        self.assertIsNone(image_size("/uploads/nonexistent.jpg"))
        self.assertIsNone(image_size("/uploads/../outside.jpg"))

    def test_03_submission_missing_cover(self):
        body = {
            "items": [{
                "kind": "style",
                "name": "缺封面画风",
                "definition": "测试定义",
                "images": ["/images/FA-001.webp"],
            }]
        }
        with self.assertRaises(S.ServiceError) as ctx:
            C.submit(self.db, self.author, body)
        self.assertEqual(ctx.exception.code, "missing_cover")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("请上传一张正方形封面图", ctx.exception.message)

    def test_04_submission_external_cover(self):
        body = {
            "items": [{
                "kind": "style",
                "name": "外链封面画风",
                "definition": "测试定义",
                "cover": "https://external.test/cover.jpg",
                "images": ["/images/FA-001.webp"],
            }]
        }
        with self.assertRaises(S.ServiceError) as ctx:
            C.submit(self.db, self.author, body)
        self.assertEqual(ctx.exception.code, "cover_external")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("封面请上传到本站，不能使用外部链接", ctx.exception.message)

    def test_05_submission_cover_not_square_with_dimensions(self):
        rec_url = self._create_img("rec.jpg", 1200, 900)
        body = {
            "items": [{
                "kind": "style",
                "name": "长方形封面画风",
                "definition": "测试定义",
                "cover": rec_url,
                "images": ["/images/FA-001.webp"],
            }]
        }
        with self.assertRaises(S.ServiceError) as ctx:
            C.submit(self.db, self.author, body)
        self.assertEqual(ctx.exception.code, "cover_not_square")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("1200×900", ctx.exception.message)

    def test_06_submission_tolerance_success(self):
        tol_url = self._create_img("tol.jpg", 1000, 1006)
        body = {
            "items": [{
                "kind": "style",
                "name": "容差内封面画风",
                "definition": "测试定义",
                "cover": tol_url,
                "images": ["/images/FA-001.webp"],
            }]
        }
        res = C.submit(self.db, self.author, body)
        self.assertTrue(res["ok"])
        sid = res["submissions"][0]["id"]
        vrow = self.db.get_conn().execute("SELECT payload_json FROM curation_versions WHERE submission_id=?", (sid,)).fetchone()
        payload = json.loads(vrow[0])
        self.assertEqual(payload["cover"], tol_url)
        self.assertEqual(payload["image"], tol_url)
        self.assertEqual(payload["images"], ["/images/FA-001.webp"])
        self.assertNotIn(tol_url, payload["images"])

    def test_07_single_item_only_validation(self):
        sq1 = self._create_img("sq1.jpg", 400, 400)
        sq2 = self._create_img("sq2.jpg", 400, 400)
        body = {
            "items": [
                {"kind": "style", "name": "画风1", "definition": "定1", "cover": sq1},
                {"kind": "layout", "name": "图型1", "definition": "定2", "cover": sq2},
            ]
        }
        with self.assertRaises(S.ServiceError) as ctx:
            C.submit(self.db, self.author, body)
        self.assertEqual(ctx.exception.code, "single_item_only")
        self.assertEqual(ctx.exception.status, 400)

    def test_08_too_many_example_images(self):
        sq = self._create_img("sq_ex.jpg", 400, 400)
        body = {
            "items": [{
                "kind": "style",
                "name": "多图画风",
                "definition": "定义",
                "cover": sq,
                "images": [f"/images/img_{i}.webp" for i in range(10)],
            }]
        }
        with self.assertRaises(S.ServiceError) as ctx:
            C.submit(self.db, self.author, body)
        self.assertEqual(ctx.exception.code, "too_many_images")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("示例图最多 9 张", ctx.exception.message)

    def test_09_catalog_community_entry_square_enforcement(self):
        rec_url = self._create_img("rec_comm.jpg", 1200, 900)
        comm_body = {
            "kind": "style",
            "name": "社区画风",
            "definition": "定义",
            "cover": rec_url,
            "images": ["/images/FA-001.webp"],
        }
        with self.assertRaises(S.ServiceError) as ctx:
            S.publish_user_community_asset(self.db, self.author, comm_body)
        self.assertEqual(ctx.exception.code, "cover_not_square")
        self.assertIn("1200×900", ctx.exception.message)

    def test_10_publish_approval_and_topic_images(self):
        sq = self._create_img("sq_pub.jpg", 500, 500)
        body = {
            "items": [{
                "kind": "style",
                "name": "可收录画风",
                "definition": "定义内容",
                "cover": sq,
                "images": ["/images/FA-001.webp", "/images/FA-002.webp"],
            }]
        }
        res = C.submit(self.db, self.author, body)
        sid = res["submissions"][0]["id"]
        tid = res["topicId"]

        trow = self.db.get_conn().execute("SELECT images_json FROM forum_topics WHERE id=?", (tid,)).fetchone()
        t_images = json.loads(trow[0])
        self.assertEqual(t_images[0], sq)
        self.assertEqual(t_images[1:], ["/images/FA-001.webp", "/images/FA-002.webp"])

        with self.db.transaction() as tx:
            sub_row = C._submission_row(tx, sid)
            pub_res = C._publish_approved(tx, sub_row, 1)
        self.assertEqual(pub_res["code"], res["submissions"][0]["targetId"])
        asset_row = self.db.get_conn().execute("SELECT image_url FROM catalog_assets WHERE code=?", (res["submissions"][0]["targetId"],)).fetchone()
        self.assertEqual(asset_row["image_url"], sq)

    def test_11_legacy_version_approval_without_square_check(self):
        # Insert a legacy version with non-square image without cover
        non_sq = self._create_img("legacy_rec.jpg", 1200, 900)
        ex2 = "/images/FA-002.webp"
        sid = "legacy_sub_01"
        target_id = "USR-S-LEGACY"
        tid = "topic_legacy"
        now = C._now()

        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO curation_submissions (id, topic_id, owner_username, owner_user_id, kind, target_id, status, current_revision, request_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'style', ?, 'pending', 1, '', ?, ?)",
                (sid, tid, self.author["username"], self.author["id"], target_id, now, now),
            )
            legacy_payload = {
                "kind": "style",
                "name": "旧版画风",
                "definition": "旧版定义",
                "images": [non_sq, ex2],
            }
            tx.execute(
                "INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at) VALUES ('ver_leg', ?, 1, ?, ?)",
                (sid, json.dumps(legacy_payload, ensure_ascii=False), now),
            )
            tx.execute(
                "INSERT INTO forum_topics (id, category, category_label, pinned, featured, title, author_username, author_name, views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id, images_json, styles_json, layout_code, work_id, recipe_json, recipe_has_secret, summary, locked_body, status, published_at_ms, created_label, created_at, updated_at) VALUES (?, 'assets', '🎨 画风与图型专区', 0, 0, '旧版帖', ?, ?, 0, 0, 0, 0, 0, 'none', 0, '', ?, '[]', '', '', '', 0, '简介', '', 'published', 1000, '刚刚', ?, ?)",
                (tid, self.author["username"], self.author["username"], json.dumps([non_sq, ex2]), now, now),
            )
            # Admin approval of legacy payload succeeds without checking square
            sub_row = C._submission_row(tx, sid)
            pub_res = C._publish_approved(tx, sub_row, 1)
        self.assertEqual(pub_res["code"], target_id)
        row = self.db.get_conn().execute("SELECT image_url FROM catalog_assets WHERE code=?", (target_id,)).fetchone()
        self.assertEqual(row["image_url"], non_sq)

    def test_12_legacy_revise_requires_square_cover(self):
        # When revising, the reused non-square cover must be rejected
        non_sq = self._create_img("legacy_rec2.jpg", 1200, 900)
        sq = self._create_img("new_square.jpg", 600, 600)
        sid = "legacy_sub_02"
        target_id = "USR-S-LEGACY2"
        tid = "topic_legacy2"
        now = C._now()

        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO curation_submissions (id, topic_id, owner_username, owner_user_id, kind, target_id, status, current_revision, request_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'style', ?, 'approved', 1, '', ?, ?)",
                (sid, tid, self.author["username"], self.author["id"], target_id, now, now),
            )
            tx.execute(
                "INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at) VALUES ('ver_leg2', ?, 1, ?, ?)",
                (sid, json.dumps({"kind": "style", "name": "旧版", "definition": "旧定", "images": [non_sq]}, ensure_ascii=False), now),
            )
            tx.execute(
                "INSERT INTO forum_topics (id, category, category_label, pinned, featured, title, author_username, author_name, views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id, images_json, styles_json, layout_code, work_id, recipe_json, recipe_has_secret, summary, locked_body, status, published_at_ms, created_label, created_at, updated_at) VALUES (?, 'assets', '🎨 画风与图型专区', 0, 0, '旧版帖', ?, ?, 0, 0, 0, 0, 0, 'none', 0, '', '[]', '[]', '', '', '', 0, '简介', '', 'published', 1000, '刚刚', ?, ?)",
                (tid, self.author["username"], self.author["username"], now, now),
            )

        # Revise with existing non-square cover -> 400 cover_not_square
        with self.assertRaises(S.ServiceError) as ctx:
            C.revise(self.db, self.author, sid, {
                "payload": {"name": "新版", "definition": "旧定", "cover": non_sq, "images": []}
            })
        self.assertEqual(ctx.exception.code, "cover_not_square")

        # Replace with square cover -> revise succeeds (status 200)
        rev_res = C.revise(self.db, self.author, sid, {
            "payload": {"name": "新版", "definition": "旧定", "cover": sq, "images": []}
        })
        self.assertTrue(rev_res["ok"])
        self.assertEqual(rev_res["revision"], 2)


if __name__ == "__main__":
    unittest.main()
