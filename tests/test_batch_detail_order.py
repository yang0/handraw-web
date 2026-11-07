"""Batch detail must use the source image order on both supported databases."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.db import Database
from backend.generation_works import derive_item_key
from backend.post_routes import _handle_detail
from backend.services import register_user
from backend.works_feed import get_work_by_id

GENERATION = 'batch_order_regression'
IMAGE = '/images/individual/FA/FA-013.webp'


def seed_batch_detail(db):
    user, _ = register_user(db, 'batch_order_author', 'IsolatedBatchPassword!')
    items = [{'id': 'z_first', 'imageUrl': IMAGE}, {'imageUrl': IMAGE + '?variant=second'},
             {'id': 'hidden_third', 'imageUrl': IMAGE + '?variant=hidden'}]
    now = '2026-11-07T00:00:00Z'
    with db.transaction() as tx:
        tx.execute(
            """INSERT INTO studio_generations
               (id,user_id,username,tab_title,mode,mode_label,kind,recipe_summary,prompt,items_json,
                engine,cost_type,credits_spent,status,created_at,request_id,visibility)
               VALUES(?,?,?,'Batch','pure','Pure','single','','',?,'live','free',0,'success',?,'batch-order-request','public')""",
            (GENERATION, user['id'], user['username'], json.dumps(items), now),
        )
        # Reversed insertion and key order deliberately disagree with source image order.
        for index in (1, 0, 2):
            work_id, topic_id = f'batch_work_{index}', f'batch_topic_{index}'
            tx.execute(
                """INSERT INTO works
                   (id,author_username,author_name,title,prompt,images_json,status,published_at_ms,created_at,updated_at)
                   VALUES(?,?,?,'Batch work','',?,?,1,?,?)""",
                (work_id, user['username'], 'Test Author', json.dumps([IMAGE]),
                 'hidden' if index == 2 else 'published', now, now),
            )
            tx.execute(
                "INSERT INTO generation_works(generation_id,item_key,work_id,created_at) VALUES(?,?,?,?)",
                (GENERATION, derive_item_key(items[index], index)[0], work_id, now),
            )
            tx.execute(
                """INSERT INTO forum_topics
                   (id,category,category_label,title,author_username,author_name,summary,status,work_id,
                    listed_at_ms,published_at_ms,created_at,updated_at)
                   VALUES(?,'assets','Assets','Batch topic',?,'Test Author','','published',?,1,1,?,?)""",
                (topic_id, user['username'], work_id, now, now),
            )
            tx.execute(
                "INSERT INTO curation_resource_topics(kind,target_id,topic_id,origin,created_at) VALUES('work',?,?,'submission',?)",
                (work_id, topic_id, now),
            )


def assert_batch_detail_order(test, db):
    payloads = []
    handler = SimpleNamespace(db=db, _current_user=lambda required=False: None, _send_json=payloads.append)
    for index in (0, 1):
        test.assertTrue(_handle_detail(handler, f'batch_topic_{index}'))
        batch = payloads[-1]['mount']['work']['batchWorks']
        test.assertEqual([row['workId'] for row in batch], ['batch_work_0', 'batch_work_1'])
        test.assertEqual([row['index'] for row in batch], [1, 2])
        test.assertTrue(batch[index]['isCurrent'])
        work = get_work_by_id(db, f'batch_work_{index}')
        test.assertEqual(work['batchIndex'], index + 1)
        test.assertEqual(work['batchTotal'], 2)


class BatchDetailOrderTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'HANDRAW_DEMO_MODE': '0'}))
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'batch.db')
        self.db.migrate()
        seed_batch_detail(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_post_and_work_detail_share_source_order_without_writes(self):
        before = self.db.get_conn().total_changes
        assert_batch_detail_order(self, self.db)
        self.assertEqual(self.db.get_conn().total_changes, before)

    def test_bad_source_json_uses_deterministic_fallback(self):
        from backend.generation_works import sort_generation_batch_works
        self.db.get_conn().execute('UPDATE studio_generations SET items_json=? WHERE id=?', ('invalid', GENERATION))
        rows = [{'item_key': 'z', 'mapped_at': 'same', 'work_id': 'last'},
                {'item_key': 'a', 'mapped_at': 'same', 'work_id': 'first'}]
        with self.assertLogs('handraw.generation_works', level='WARNING'):
            ordered = sort_generation_batch_works(self.db.get_conn(), GENERATION, rows)
        self.assertEqual([row['work_id'] for row in ordered], ['first', 'last'])


if __name__ == '__main__':
    unittest.main()
