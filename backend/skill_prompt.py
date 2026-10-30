"""Build an image prompt through the hand-drawn style Skill's own data.

The Skill's contract is that an image is never generated straight from a style
label: the style's traits, the layout's composition rules and the colour all
have to be resolved first, and only then does a prompt go to the image model.

This module is that step for the website.  It reads the Skill package's own
reference files (no duplicated copy of the catalogue) and asks the configured
text model to write the prompt, so the result follows the same rules a
conversational Skill run would produce.  When no text model is configured it
falls back to a deterministic template built from the same data.
"""
from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import load_ai_config
from .skill_paths import SKILL_DIR, reference_file

# The Skill package is a separate checkout (see skill_paths.SKILL_REPO).
SKILL_ROOT = SKILL_DIR
REFERENCES = SKILL_DIR / "references"


def _read_json(name: str) -> Any:
    path = reference_file(name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def _styles() -> list[dict]:
    data = _read_json("styles.json")
    return data if isinstance(data, list) else []


@lru_cache(maxsize=1)
def _layouts() -> list[dict]:
    data = _read_json("layouts.json")
    return data if isinstance(data, list) else []


@lru_cache(maxsize=1)
def _colors() -> list[dict]:
    data = _read_json("colors.json")
    return data if isinstance(data, list) else []


def skill_available() -> bool:
    return bool(_styles())


def find_style(code: str) -> dict | None:
    """Resolve 'FA-013', '013' or '#013' to a style entry.

    ``styles.json`` stores the canonical code in ``number`` (e.g. ``FA-001``);
    plain three-digit numbers are accepted for convenience.
    """
    raw = str(code or "").strip().upper().lstrip("#")
    if not raw:
        return None
    for style in _styles():
        key = str(style.get("number") or "").strip().upper()
        if key == raw:
            return style
        # '013' should find 'FA-013' only when unambiguous.
    if raw.isdigit():
        matches = [
            s for s in _styles()
            if str(s.get("number") or "").upper().endswith("-" + raw.zfill(3))
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def find_layout(code: str) -> dict | None:
    raw = str(code or "").strip().upper()
    if not raw:
        return None
    for layout in _layouts():
        if str(layout.get("id") or "").upper() == raw:
            return layout
    return None


def _layout_rules(code: str) -> str:
    """The layout's own composition prompt, from its Markdown definition."""
    layout = find_layout(code)
    if not layout:
        return ""
    rel = str(layout.get("prompt_file") or "")
    for base in (SKILL_ROOT, SKILL_ROOT / "references"):
        path = (base / rel) if rel else None
        if path and path.is_file():
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
    return str(layout.get("name") or "")


def build_facts(style_code: str, layout_code: str = "", colour: str = "", theme: str = "") -> dict:
    """Collect everything the Skill would consider before writing a prompt."""
    style = find_style(style_code) or {}
    layout = find_layout(layout_code) or {}
    return {
        "theme": str(theme or "").strip(),
        "style": {
            "id": str(style.get("number") or style_code or ""),
            "name": style.get("generation_name") or "",
            "group": style.get("group") or "",
            "traits": style.get("traits") or "",
            "reference": style.get("reference") or "",
        },
        "layout": {
            "id": layout.get("id") or layout_code,
            "name": layout.get("name") or "",
            "name_en": layout.get("name_en") or "",
            "rules": _layout_rules(layout_code) if layout_code else "",
        },
        "colour": str(colour or ""),
    }


def _call_model(system: str, user: str, *, timeout: int = 120) -> str:
    cfg = load_ai_config()
    base = str(cfg.get("url") or "").rstrip("/")
    key = str(cfg.get("key") or "")
    model = str(cfg.get("model") or "")
    if not base or not key:
        return ""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 1200,
        "temperature": 0.4,
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"]).strip()
    except Exception:
        return ""


_SYSTEM = (
    "You write image-generation prompts for a hand-drawn illustration library. "
    "You are given the chosen style's traits and the chosen layout's composition "
    "rules. Produce ONE English prompt that honours both: the style controls "
    "linework, palette and texture; the layout controls composition, framing, "
    "negative space and any typography. Never invent a different style, never "
    "mention the reference artist's name, and never output commentary. "
    "Output the prompt text only."
)


def _template(facts: dict) -> str:
    """Deterministic fallback built from the same Skill data."""
    parts: list[str] = []
    style = facts["style"]
    layout = facts["layout"]
    if style.get("name"):
        parts.append(f"Hand-drawn illustration in the style '{style['name']}'")
    if style.get("traits"):
        parts.append(str(style["traits"]).strip())
    if facts.get("colour"):
        parts.append(f"dominant colour: {facts['colour']}")
    if facts.get("theme"):
        parts.append(f"Subject: {facts['theme']}")
    if layout.get("name_en") or layout.get("name"):
        parts.append(f"Composition follows the layout '{layout.get('name_en') or layout['name']}'")
    if layout.get("rules"):
        rules = " ".join(str(layout["rules"]).split())
        parts.append(rules[:900])
    parts.append("No signature, no watermark, no artist name in the image.")
    return ". ".join(p for p in parts if p)


def compose_prompt(style_code: str, layout_code: str = "", colour: str = "", theme: str = "") -> dict:
    """Return ``{prompt, source, facts}`` for one image request.

    ``source`` is ``"model"`` when the text model wrote the prompt and
    ``"template"`` when the deterministic fallback was used, so callers can tell
    how much to trust the wording.
    """
    facts = build_facts(style_code, layout_code, colour, theme)
    if not facts["theme"]:
        return {"prompt": "", "source": "none", "facts": facts}
    # Without a resolved style or layout there is nothing for the Skill to
    # contribute; answering anyway produced a chat reply ("please provide more
    # information") that looked like a prompt.
    if not facts["style"]["name"] and not facts["layout"]["name"]:
        return {"prompt": "", "source": "none", "facts": facts}

    user = (
        f"Style id: {facts['style']['id']}\n"
        f"Style name: {facts['style']['name']}\n"
        f"Style traits: {facts['style']['traits']}\n"
        f"Layout id: {facts['layout']['id']}\n"
        f"Layout name: {facts['layout']['name']}\n"
        f"Layout composition rules: {facts['layout']['rules'][:4000]}\n"
        f"Colour: {facts['colour'] or 'not specified'}\n"
        f"Subject / theme (may be Chinese): {facts['theme']}\n"
    )
    text = _call_model(_SYSTEM, user)
    if text and _looks_like_prompt(text):
        return {"prompt": text, "source": "model", "facts": facts}
    return {"prompt": _template(facts), "source": "template", "facts": facts}


# A reply that asks for more information is not a prompt.  The model sometimes
# answers a thin request with "please provide the style name", which would then
# be sent to the image model verbatim.
_REFUSAL_MARKERS = (
    "请补充",
    "请提供",
    "需要更多",
    "信息不足",
    "无法生成",
    "please provide",
    "need more information",
    "cannot generate",
    "could you provide",
)


def _looks_like_prompt(text: str) -> bool:
    body = text.strip()
    if len(body) < 40:
        return False
    lowered = body.lower()
    if any(marker in lowered for marker in _REFUSAL_MARKERS):
        return False
    return True
