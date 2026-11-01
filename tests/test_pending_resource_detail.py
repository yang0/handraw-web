"""A pending submission still owns its discussion topic.

Publishing a style or layout sends the author straight to the new topic, but the
catalogue entry does not exist until a moderator approves it. Without a fallback
the detail endpoint answered 404 right after publishing, so the browser showed
"帖子不存在或已不可见" and publishing looked broken.
"""
import unittest

from tests import test_v2_curation as fixtures
from backend import curation as C, resource_discussions as D


class PendingResourceDetailTests(unittest.TestCase):
    setUp = fixtures.CurationTests.setUp
    tearDown = fixtures.CurationTests.tearDown
    item = fixtures.CurationTests.item

    def _submission(self):
        result = C.submit(self.db, self.author, {
            'title': '待审资源帖',
            'text': '公开介绍',
            'items': [self.item('style')],
        })
        sub = result['submissions'][0]
        return sub['targetId'], result['topicId']

    def test_pending_style_resolves_for_the_topic_page(self):
        target_id, _topic_id = self._submission()
        conn = self.db.get_conn()

        # Existing callers keep the old answer: the catalogue entry is not live.
        self.assertIsNone(D.resolve_resource(conn, 'style', target_id))

        raw = D.resolve_resource(conn, 'style', target_id, include_pending=True)
        self.assertIsNotNone(raw, 'a pending submission must resolve for its own topic')
        assert raw is not None
        self.assertEqual(raw['name'], '纸上微光')
        self.assertTrue(raw['pending'])
        self.assertNotIn('code', raw, 'the static branch renders submissions')

    def test_pending_definition_is_owner_only(self):
        target_id, _topic_id = self._submission()
        conn = self.db.get_conn()

        anonymous = D.resolve_resource(conn, 'style', target_id, include_pending=True)
        assert anonymous is not None
        self.assertEqual(anonymous['definition'], '')
        self.assertTrue(anonymous['definitionHidden'])

        stranger = D.resolve_resource(
            conn, 'style', target_id, viewer={'username': 'someone_else'}, include_pending=True)
        assert stranger is not None
        self.assertEqual(stranger['definition'], '')

        owner = D.resolve_resource(
            conn, 'style', target_id, viewer=self.author, include_pending=True)
        assert owner is not None
        self.assertIn('秘密定义', owner['definition'])
        self.assertFalse(owner['definitionHidden'])

    def test_withdrawn_submission_does_not_resolve(self):
        target_id, _topic_id = self._submission()
        with self.db.transaction() as tx:
            tx.execute("UPDATE curation_submissions SET status='withdrawn' WHERE UPPER(target_id)=?",
                       (target_id.upper(),))
        self.assertIsNone(
            D.resolve_resource(self.db.get_conn(), 'style', target_id, include_pending=True))
