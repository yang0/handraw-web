"""#111: disposable heavy-media fixture derived from checked-in test WebPs.

These assets are *only* for isolated Chromium performance tests. No generated
test media is committed, exposed to production, or uploaded to CI artifacts.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    ROOT / "demo/starter/bear-and-bird.webp",
    ROOT / "demo/starter/clay-commuter.webp",
    ROOT / "demo/starter/skate-boy.webp",
)


def make_distinct_webp(output_dir: Path, count: int = 120,
                       size: tuple[int, int] = (960, 720)) -> dict:
    """Create distinct, *locally served* WebP URLs with independent bytes.

    The artwork is from the repository's existing test imagery. Deterministic
    crops/brightness only distinguish decoding/cache entries, not new art.
    Keep sizes bounded to prevent CI memory/CPU exhaustion.
    """
    from PIL import Image, ImageEnhance, ImageOps

    output_dir = Path(output_dir)
    if not (1 <= count <= 120 and 16 <= size[0] <= 1024 and
            16 <= size[1] <= 1024):
        raise ValueError("unsafe benchmark media dimensions or count")
    if not all(path.is_file() for path in SOURCES):
        raise FileNotFoundError("repository WebP source missing")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("output media directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)

    decoded_sources = []
    try:
        for source in SOURCES:
            with Image.open(source) as img:
                decoded_sources.append(img.convert("RGB"))
        hashes, urls, total_bytes = set(), [], 0
        for i in range(count):
            base = decoded_sources[i % len(decoded_sources)]
            crop_x = 0.35 + (i % 7) * .05
            crop_y = 0.35 + (i % 11) * .03
            image = ImageOps.fit(base, size, method=Image.Resampling.BILINEAR,
                                 centering=(crop_x, crop_y))
            adjusted = ImageEnhance.Brightness(image).enhance(.78 + (i + 1) * .003)
            target = output_dir / f"qa111-{i:03d}.webp"
            adjusted.save(target, "WEBP", quality=68, method=0)
            adjusted.close()
            image.close()
            payload = target.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest in hashes:
                raise AssertionError("distinct-media fixture accidentally deduplicated")
            hashes.add(digest)
            total_bytes += len(payload)
            urls.append(f"/starter/{output_dir.name}/{target.name}")
        return {
            "urls": urls,
            "count": count,
            "sourceFixtureCount": len(SOURCES),
            "decodedPixelsExpected": count * size[0] * size[1],
            "encodedBytes": total_bytes,
            "uniqueSha256": len(hashes),
            "isProductionMedia": False,
        }
    finally:
        for img in decoded_sources:
            img.close()


def apply_distinct_media(graph: dict, urls: list[str]) -> int:
    """Assign one distinct URL to each native asset/output image slot."""
    idx = 0
    for node in graph["nodes"]:
        data = node.get("data") or {}
        if node["type"] == "asset":
            for item in data.get("items") or []:
                if idx >= len(urls):
                    raise ValueError("not enough unique benchmark media")
                item["image"] = urls[idx]
                idx += 1
        elif node["type"] == "output_display":
            for item in data.get("items") or []:
                if idx >= len(urls):
                    raise ValueError("not enough unique benchmark media")
                item["imageUrl"] = urls[idx]
                idx += 1
    if idx != len(urls):
        raise AssertionError(f"fixture slots {idx} != unique URLs {len(urls)}")
    return idx
