"""Where the hand-drawn style Skill lives.

The website never hard-codes a copy of the style catalogue: it reads the Skill's
own reference files so the prompts it builds follow the same rules a
conversational Skill run would produce.

Source of truth: https://github.com/yang0/handraw-style
To update the Skill, pull that repository and refresh the local checkout below;
no website change is needed unless the reference file layout itself changes.
"""
from __future__ import annotations

import os
from pathlib import Path

# Canonical location of the Skill package.
SKILL_REPO = "https://github.com/yang0/handraw-style"

# Local checkout of the package.  Override with HANDRAW_STYLE_SKILL_DIR when the
# checkout lives elsewhere (the deployed server will, for example).
SKILL_DIR = Path(
    os.environ.get(
        "HANDRAW_STYLE_SKILL_DIR",
        r"E:\handraw-style\skills\handdraw-style-prompter",
    )
)

REFERENCES_DIR = SKILL_DIR / "references"


def reference_file(name: str) -> Path:
    return REFERENCES_DIR / name
