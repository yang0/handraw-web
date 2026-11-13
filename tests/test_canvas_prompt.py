"""Canvas mode semantics preserve user facts and deterministic gateway inputs."""

import unittest

from backend.canvas_prompt import (
    GRAPHIC_TEXT_SUFFIX,
    PURE_IMAGE_RULE,
    build_canvas_prompt,
)
from backend.services import ServiceError
from backend.studio_canvases import compile_canvas
from tests.test_studio_canvases import graph


class CanvasPromptTests(unittest.TestCase):
    def test_modes_preserve_theme_and_put_the_skill_rule_after_resource_instructions(
        self,
    ):
        theme = "项目预算350万\n6人到20人，每个数字保持原样。"
        for mode in ("image-only", "graphic-text", "poster"):
            with self.subTest(mode=mode):
                text = build_canvas_prompt(
                    theme,
                    {"mode": mode, "ratio": "16:9"},
                    ["trusted resource instructions"],
                )
                self.assertIn("主题：" + theme, text)
                self.assertIn("trusted resource instructions", text)
                self.assertIn("16:9", text)
                self.assertTrue(
                    text.endswith(
                        PURE_IMAGE_RULE if mode == "image-only" else GRAPHIC_TEXT_SUFFIX
                    )
                )
                if mode == "poster":
                    self.assertIn("【业务场景】：海报", text)
                    self.assertIn("标题层级", text)
                elif mode == "image-only":
                    self.assertNotIn(GRAPHIC_TEXT_SUFFIX, text)

    def test_catalog_names_and_custom_values_reach_the_prompt_without_raw_codes(self):
        text = build_canvas_prompt(
            "猫咪",
            {
                "colors": ["C-01", "自定义暖灰"],
                "tones": ["T-01", "柔和逆光"],
                "moods": ["治愈"],
                "whitespace": "high",
            },
        )
        for value in (
            "克莱因蓝",
            "自定义暖灰",
            "影调",
            "高调",
            "柔和逆光",
            "治愈",
            "大量留白",
        ):
            self.assertIn(value, text)
        self.assertNotIn("C-01", text)
        self.assertNotIn("T-01", text)

    def test_compiler_freezes_all_three_modes_as_separate_combinations(self):
        document = graph(
            ("prompt", ["One"]), ("mode", ["image-only", "graphic-text", "poster"])
        )
        items = compile_canvas(document)
        self.assertEqual(
            [item["spec"]["mode"] for item in items],
            ["image-only", "graphic-text", "poster"],
        )
        document["nodes"][1]["values"] = ["unsupported"]
        with self.assertRaises(ServiceError):
            compile_canvas(document)
