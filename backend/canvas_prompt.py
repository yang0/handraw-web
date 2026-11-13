"""Deterministic canvas prompts from the frozen input and Handraw mode rules."""

from __future__ import annotations

import json
from functools import lru_cache

from .config import CONTENT_DIR

# Handraw Skill / scripts/prompt_style.py and poster-prompt-generator/SKILL.md.
GRAPHIC_TEXT_SUFFIX = "【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。 如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，由你先设计画面隐喻（人类和非人类都行）再出图   。    文字参与构图，图文一体】"
PURE_IMAGE_RULE = (
    "【纯图模式：只绘制与主题相符的画面，不添加标题、标语、说明文字或装饰性字符。】"
)
WHITESPACE = {"normal": "正常留白", "moderate": "适中留白", "high": "大量留白"}


@lru_cache(maxsize=1)
def parameter_names():
    names = {}
    for filename, group in (
        ("catalog.json", "resources"),
        ("studio-options.json", "tones"),
    ):
        try:
            data = json.loads((CONTENT_DIR / filename).read_text(encoding="utf-8"))
            for item in data.get(group, []):
                code = str(item.get("id") or item.get("code") or "")
                name = item.get("name_zh") or item.get("name") or ""
                if code and name:
                    names[code] = str(name)
        except (OSError, ValueError, TypeError):
            continue
    return names


def build_canvas_prompt(theme, spec, instructions=()):
    """Keep the theme verbatim; trusted resource instructions stay server-side."""
    names = parameter_names()
    mode = spec.get("mode") or "graphic-text"
    mode_name = {"image-only": "纯图", "graphic-text": "图文", "poster": "海报"}[mode]
    parts = [f"【创作模式】：{mode_name}", f"主题：{theme}"]
    for key, label in (("colors", "主题色"), ("tones", "影调"), ("moods", "情感基调")):
        values = spec.get(key) or []
        if values:
            parts.append(
                f"【{label}】："
                + "、".join(names.get(value, value) for value in values)
            )
    if spec.get("ratio"):
        parts.append(f"【画幅比例】：{spec['ratio']}")
    if spec.get("whitespace"):
        value = spec["whitespace"]
        parts.append(f"【留白】：{WHITESPACE.get(value, value)}")
    if mode == "poster":
        parts.extend(
            [
                "【业务场景】：海报",
                "【排版要求】：围绕主题自主设计海报的主视觉、标题层级和文字排版，保持信息清晰；只使用用户提供的事实、数字和文案，不编造品牌、活动时间、价格或联系方式。",
            ]
        )
    parts.extend(str(value).strip() for value in instructions if str(value).strip())
    parts.append(PURE_IMAGE_RULE if mode == "image-only" else GRAPHIC_TEXT_SUFFIX)
    return "\n\n".join(parts)
