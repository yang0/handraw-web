"""Generate the ten starter works' illustrations with the image service.

The site previously reused style-gallery covers as work images, so titles and
pictures disagreed.  This script asks the image model for a fresh picture for
each work, using the style's own description plus a concrete subject, and saves
it under ``demo/generated/starter/`` so the work, its text and its picture all
refer to the same thing.

Usage:
    python -X utf8 ops/generate_starter_images.py
    python -X utf8 ops/generate_starter_images.py --only FA-013 FE-012
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

IMAGE_CLIENT_DIR = Path(r"E:\projectHome\handraw-fabu\style\scripts")
OUT_DIR = Path(__file__).resolve().parent.parent / "demo" / "generated" / "starter"

# style code -> (file stem, English prompt)
JOBS: list[tuple[str, str, str]] = [
    (
        "FA-013",
        "surfer-boy",
        "Bold flat everyday satire illustration: a joyful kid holding a long yellow surfboard "
        "under one arm, wearing a blue cap and white t-shirt, raising the other hand in a peace "
        "sign, warm brown skin, black curly hair, thick black outlines, flat color blocks, "
        "pure white background, no text, no signature.",
    ),
    (
        "FE-012",
        "qipao-red-sun",
        "Contemporary Chinese cultural editorial illustration: profile of a woman with a "
        "traditional updo in a black high-collar qipao, a large vermilion sun disc behind her, "
        "a white crane flying past on the left, distant Chinese pavilions, muted ink tones "
        "with cinnabar red accents, paper texture, generous negative space, no text.",
    ),
    (
        "FB-028",
        "writer-and-duck",
        "Loose ink and gouache storybook studio scene: a shaggy-haired bearded man in a dark "
        "vest writing in a notebook at a wooden desk, a small white duck standing beside a "
        "pencil cup, red telephone box and bookshelf in the background, warm lamplight, "
        "loose confident brush lines over watercolour washes, paper grain, no text.",
    ),
    (
        "FG-004",
        "castle-guards",
        "Vintage 1970s European hand-drawn animation cel: two comical guards before a rough "
        "stone archway, one broad-faced with a big red moustache in green uniform and cap, the "
        "other thin wearing a tall pointed white hat and a monocle, clean outlines, soft cel "
        "shading, muted earthy palette, lighthearted satire, no text.",
    ),
    (
        "FE-030",
        "skate-boy",
        "Free-line urban youth comic: a young man in a backwards baseball cap sitting on a "
        "skateboard, oversized white hoodie, loose black trousers, chunky sneakers, black "
        "backpack beside him, graffiti wall and grey buildings behind, cool grey palette, "
        "crisp confident linework, no text.",
    ),
    (
        "FE-005",
        "seaside-wall",
        "Soft seasonal travel watercolour diary: seen from behind, a short-haired girl and a "
        "black cat sitting on a pale stone sea wall, bright turquoise sea and white boat ahead, "
        "a whitewashed town with orange roofs stacked along the cliff on the right, thin clouds, "
        "transparent layered washes, soft edges, paper texture, no text.",
    ),
    (
        "FD-016",
        "notebook-doodle",
        "Notebook lifestyle doodle: a girl with a messy bun lying on the floor writing in an "
        "open spiral notebook, striped tee and jeans, mug, small potted plant and a sleeping "
        "tabby cat around her, hand-drawn stars and a smiley face scattered about, thin brown "
        "lines on warm off-white paper, no text.",
    ),
    (
        "FI-008",
        "riviera-portrait",
        "Sun-drenched minimal fashion photography, French Riviera: a woman in a wide straw hat "
        "and sunglasses sitting on white stone steps, flowing cream dress, deep blue sea and "
        "distant islands behind, an olive tree at right, hard midday light and crisp shadows, "
        "high-key blue and white palette, no text.",
    ),
    (
        "FB-041",
        "bear-and-bird",
        "Textured paper watercolour storybook: a round brown bear cub sitting on a mossy stone "
        "beside a stream, one paw extended with a tiny bird perched in it, backlit conifer "
        "forest and flowing water behind, warm golden morning mist, grainy paper texture, "
        "soft focus, tender mood, no text.",
    ),
    (
        "FF-006",
        "clay-commuter",
        "Deadpan stylized 3D clay character: a commuter in a blue suit over a white shirt with a "
        "black tie standing at a crossing, holding a takeaway coffee cup, exaggerated drooping "
        "eyelids and a long sculpted jaw, matte clay surface, blurred street behind (yellow cab, "
        "traffic light, fire hydrant), soft studio lighting, no text.",
    ),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate starter work illustrations.")
    parser.add_argument("--only", nargs="*", help="Only generate these style codes")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="medium")
    args = parser.parse_args(argv)

    if not IMAGE_CLIENT_DIR.is_dir():
        print(f"image client not found: {IMAGE_CLIENT_DIR}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(IMAGE_CLIENT_DIR))
    import image_client as ic  # noqa: E402

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = ic.load_image_config()
    config["driver"] = "http"

    jobs = [j for j in JOBS if not args.only or j[0] in args.only]
    made, failed = 0, []
    for style, stem, prompt in jobs:
        target = OUT_DIR / f"{stem}.png"
        if target.is_file() and target.stat().st_size > 10_000:
            print(f"  skip {stem} (exists)")
            made += 1
            continue
        started = time.time()
        try:
            ic.generate_image(
                prompt,
                target,
                driver="http",
                config=config,
                size=args.size,
                quality=args.quality,
                timeout=300,
            )
            print(f"  ok   {stem}  {round(time.time() - started, 1)}s  {target.stat().st_size} bytes")
            made += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAIL {stem}: {type(exc).__name__} {str(exc)[:160]}")
            failed.append(stem)

    print(f"\ngenerated {made}/{len(jobs)}")
    if failed:
        print("failed:", failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
