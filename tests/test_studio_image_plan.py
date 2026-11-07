"""AI director only recommends authorized real resource IDs and never generates."""
import unittest
from unittest.mock import patch
from backend.services import ServiceError
from backend.studio_image_plan import execute_image_plan

USER = {"id": 10, "username": "test", "role": "user"}
STYLE = [{"id": "FA-001", "name": "柔和水彩", "summary": "暖色人物"}]
LAYOUT = [{"id": "SC-021", "name": "双屏排版", "summary": "前后对照"}]


class ImageDirectorTests(unittest.TestCase):
    def setUp(self):
        self.db = object()
        self.calls = []
        self.candidates = lambda db, user, subject, kind, preferred="": STYLE if kind == "style" else LAYOUT

    def run_plan(self, result='{"styleId":"FA-001","layoutId":"SC-021","ratio":"3:4","reason":"柔光适配主题"}',
                 style="", layout="", ratio="", locked=None):
        def chat_mock(messages, **kwargs):
            self.calls.append((messages, kwargs))
            return result, {"ok": True}
        with patch("backend.studio_image_plan._candidates", side_effect=self.candidates), \
             patch("backend.studio_image_plan.consume_daily_usage", return_value=True), \
             patch("backend.studio_image_plan.chat", side_effect=chat_mock):
            return execute_image_plan(self.db, USER, subject="杭州春天", selected_style=style,
                                      selected_layout=layout, ratio=ratio, locked_fields=locked or [])

    def test_only_theme_returns_structured_real_ids(self):
        data = self.run_plan()
        self.assertEqual(data["proposal"]["styleId"], "FA-001")
        self.assertEqual(data["proposal"]["layoutId"], "SC-021")
        self.assertEqual(data["proposal"]["ratio"], "3:4")
        messages, kwargs = self.calls[0]
        self.assertTrue(kwargs["json_mode"])
        self.assertNotIn("secret_blackbox_prompt", str(messages))

    def test_locked_selections_never_changed_by_model(self):
        data = self.run_plan(result='{"styleId":"FA-NOT-REAL","layoutId":"SC-NOT-REAL","ratio":"1:1"}',
                             style="FA-001", layout="SC-021", ratio="9:16",
                             locked=["style", "layout", "ratio"])
        self.assertEqual(data["proposal"]["styleId"], "FA-001")
        self.assertEqual(data["proposal"]["layoutId"], "SC-021")
        self.assertEqual(data["proposal"]["ratio"], "9:16")

    def test_unrecognized_ids_rejected_without_fallback(self):
        with self.assertRaises(ServiceError) as ctx:
            self.run_plan(result='{"styleId":"FA-999","layoutId":"SC-021","ratio":"3:4"}')
        self.assertEqual(ctx.exception.code, "image_plan_invalid")

    def test_non_json_rejected(self):
        with self.assertRaises(ServiceError) as ctx:
            self.run_plan(result="Here is a recommendation")
        self.assertEqual(ctx.exception.code, "image_plan_invalid")

    def test_token_scopes_are_not_accepted(self):
        with self.assertRaises(ServiceError) as ctx:
            execute_image_plan(object(), {"id": 10, "_auth_kind": "token"}, subject="hello")
        self.assertEqual(ctx.exception.status, 403)

    def test_empty_topic_rejected_before_usage(self):
        with self.assertRaises(ServiceError) as ctx:
            execute_image_plan(object(), USER, subject="")
        self.assertEqual(ctx.exception.code, "missing_subject")


if __name__ == "__main__":
    unittest.main()
