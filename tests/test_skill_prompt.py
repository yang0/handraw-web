"""Every image prompt must come from the hand-drawn style Skill.

The founder's rule: no path may send a picture request straight to the image
model from a style label — the Skill resolves the style's traits and the
layout's composition rules first.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from backend import skill_paths, skill_prompt
from backend.services import _compose_skill_prompt

REPO = "https://github.com/yang0/handraw-style"


class SkillPromptTests(unittest.TestCase):
    def test_the_skill_package_is_reachable(self):
        if not skill_prompt.skill_available():
            self.skipTest("hand-drawn style Skill checkout not present")
        self.assertGreater(len(skill_prompt._styles()), 100, "the style catalogue should load")
        self.assertGreater(len(skill_prompt._layouts()), 10, "the layout catalogue should load")
        self.assertEqual(skill_paths.SKILL_REPO, REPO, "the Skill's upstream repo is recorded")

    def test_a_style_and_layout_produce_a_composed_prompt(self):
        if not skill_prompt.skill_available():
            self.skipTest("hand-drawn style Skill checkout not present")
        composed = skill_prompt.compose_prompt("FA-013", "SC-021", "", "a boy holding a surfboard")
        self.assertTrue(composed["prompt"], "the Skill must return a prompt for a real style and layout")
        # Assert on the facts the Skill resolved, not on the model's wording: the
        # generated text varies between runs and asserting on it made this test
        # flake.
        self.assertEqual(composed["facts"]["style"]["id"], "FA-013")
        self.assertEqual(composed["facts"]["layout"]["id"], "SC-021")
        self.assertTrue(composed["facts"]["style"]["traits"], "the style's traits should resolve")
        self.assertTrue(composed["facts"]["layout"]["rules"], "the layout's rules should resolve")
        self.assertIn(composed["source"], ("model", "template"))

    def test_the_layout_rules_reach_the_prompt(self):
        # The point of the Skill is that the layout constrains the picture; a
        # prompt that only names the style has not used it.
        if not skill_prompt.skill_available():
            self.skipTest("hand-drawn style Skill checkout not present")
        composed = skill_prompt.compose_prompt("FA-013", "SC-021", "", "a boy holding a surfboard")
        rules = composed["facts"]["layout"]["rules"]
        self.assertTrue(len(rules) > 100, "SC-021 should carry its own composition rules")
        # The template path is deterministic, so it can be checked exactly.
        template = skill_prompt._template(composed["facts"])
        self.assertIn("SC-021", template)
        self.assertGreater(len(template), len(composed["facts"]["style"]["traits"]))

    def test_without_parameters_the_helper_returns_nothing(self):
        # An empty request must fall back, not invent a prompt.
        self.assertEqual(_compose_skill_prompt("", "", ""), "")

    def test_unknown_style_falls_back_instead_of_raising(self):
        self.assertEqual(_compose_skill_prompt("ZZ-999", "", "theme"), "")

    def test_no_hard_coded_credentials_in_the_parser(self):
        source = (Path(__file__).resolve().parent.parent / "backend" / "document_parser.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("sk-", source, "the parser must not carry a literal API key")


if __name__ == "__main__":
    unittest.main()
