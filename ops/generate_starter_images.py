"""Generate the ten starter works' illustrations, prompts written by the Skill.

The image model is never asked to invent a style from a label.  For each work
this script first resolves the style's traits and the layout's composition rules
from the hand-drawn style Skill's own reference files and asks the configured
text model to write the prompt (``backend.skill_prompt``); only that prompt goes
to the image service.

Usage:
    python -X utf8 ops/generate_starter_images.py
    python -X utf8 ops/generate_starter_images.py --only FA-013 FE-012
    python -X utf8 ops/generate_starter_images.py --prompts-only
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

IMAGE_CLIENT_DIR = Path(r"E:\projectHome\handraw-fabu\style\scripts")
OUT_DIR = ROOT / "demo" / "starter"

# style code, layout code, file stem, subject in Chinese (the Skill works from a
# theme, not from a preset prompt).
JOBS: list[tuple[str, str, str, str]] = [
    ("FA-013", "SC-021", "surfer-boy", "一个抱着黄色冲浪板的男孩，戴蓝色渔夫帽，另一只手比胜利手势，卷发，赤脚"),
    ("FE-012", "SC-021", "qipao-red-sun", "一位穿黑色高领旗袍的盘发女子侧脸，身后一轮朱红大圆日，一只白鹤飞过"),
    ("FB-028", "SC-001", "writer-and-duck", "一位头发蓬乱的胡子男人在书桌前写笔记，桌上一只白鸭站在笔筒旁，背景有红色电话亭和书架"),
    ("FG-004", "EC-002", "castle-guards", "石砌拱门前站着两个卡通卫兵，一个宽脸大胡子戴军帽，一个瘦削戴白色尖帽挂单眼镜"),
    ("FD-016", "SC-021", "notebook-doodle", "一个丸子头女孩趴在地板上写手帐，旁边有马克杯、盆栽和一只趴着的猫"),
    ("FE-005", "SC-002", "seaside-wall", "一个短发女孩背对镜头坐在海边石墙上，旁边一只黑猫，前方是湛蓝海面和白色游船"),
    ("FE-030", "SC-021", "skate-boy", "一个戴棒球帽的少年坐在滑板上，白卫衣、宽松黑裤、厚底球鞋，身旁放着背包"),
    ("FI-008", "SC-001", "riviera-portrait", "一位戴宽檐草帽和墨镜的女性坐在白色石阶上，米白色长裙，身后是深蓝海面与岛屿"),
    ("FF-006", "SC-021", "clay-commuter", "一个穿蓝色西装系黑领带的黏土质男人站在路口，一手拿着外带咖啡杯，皱眉撇嘴"),
    ("FB-041", "SC-001", "bear-and-bird", "一只毛茸茸的棕色小熊坐在溪边长满青苔的石头上，爪心里停着一只小鸟，背景是逆光针叶林"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate starter illustrations through the Skill.")
    parser.add_argument("--only", nargs="*", help="Only these style codes")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="medium")
    parser.add_argument("--prompts-only", action="store_true", help="Print the prompts, do not generate")
    args = parser.parse_args(argv)

    from backend import skill_prompt

    if not skill_prompt.skill_available():
        print("hand-drawn style Skill not found; check skill_prompt.SKILL_ROOT", file=sys.stderr)
        return 2

    jobs = [j for j in JOBS if not args.only or j[0] in args.only]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    made, failed = 0, []
    client = None
    config = None
    if not args.prompts_only:
        if not IMAGE_CLIENT_DIR.is_dir():
            print(f"image client not found: {IMAGE_CLIENT_DIR}", file=sys.stderr)
            return 2
        sys.path.insert(0, str(IMAGE_CLIENT_DIR))
        import image_client as ic  # noqa: E402

        client = ic
        config = ic.load_image_config()
        config["driver"] = "http"

    for style, layout, stem, theme in jobs:
        composed = skill_prompt.compose_prompt(style, layout, "", theme)
        prompt = composed["prompt"]
        if not prompt:
            print(f"  FAIL {stem}: no prompt from the Skill")
            failed.append(stem)
            continue
        print(f"\n--- {stem}  [{style} / {layout}]  source={composed['source']} ---")
        print(prompt[:600])
        if args.prompts_only:
            made += 1
            continue

        target = OUT_DIR / f"{stem}.png"
        started = time.time()
        try:
            client.generate_image(
                prompt,
                target,
                driver="http",
                config=config,
                size=args.size,
                quality=args.quality,
                timeout=300,
            )
            print(f"  ok {stem}  {round(time.time() - started, 1)}s  {target.stat().st_size} bytes")
            made += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAIL {stem}: {type(exc).__name__} {str(exc)[:160]}")
            failed.append(stem)

    print(f"\ndone {made}/{len(jobs)}")
    if failed:
        print("failed:", failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
