"""Build public navigation and gallery overlays without changing the static checkout."""
import argparse
import re
import shutil
from pathlib import Path

PLACEHOLDER = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%224%22 height=%223%22%3E%3Cpath fill=%22%23eeeae2%22 d=%22M0 0h4v3H0z%22/%3E%3C/svg%3E'


def build(plugin: Path, target: Path, static_root: Path):
    assets = target / 'assets'
    gallery = target / 'gallery'
    assets.mkdir(parents=True, exist_ok=True)
    gallery.mkdir(parents=True, exist_ok=True)
    for name in ('portal.js', 'portal.css', 'navigation.css', 'image-loader.js'):
        shutil.copyfile(plugin / 'public' / name, assets / name)
    revision = (plugin / 'REVISION').read_text().strip()
    navigation = (plugin / 'public/navigation.html').read_text(encoding='utf-8')
    navigation = navigation.replace('data-surface="portal"', 'data-surface="gallery"')
    navigation = navigation.replace('data-site-section="resources"', 'data-site-section="resources" aria-current="page"')
    style = f'<link rel="stylesheet" href="https://static.handraw-style.com/handraw-web/releases/{revision}/assets/navigation.css">'
    loader = f'<script src="https://static.handraw-style.com/handraw-web/releases/{revision}/assets/image-loader.js" defer></script>'
    for source in (static_root / 'gallery').iterdir():
        if source.suffix != '.html':
            if source.is_file() and source.suffix in {'.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico'}:
                shutil.copyfile(source, gallery / source.name)
            continue
        page = source.read_text(encoding='utf-8')
        page = re.sub(r'<header class="hw-header".*?</header>', '', page, flags=re.S)
        page = re.sub(r'<link[^>]+handraw-web/assets/navigation\.css[^>]*>', '', page)
        # Remove the legacy five-URL error fallback (including its load listener).
        page = re.sub(r'<script>\s*\(function\(\)\s*\{\s*function fixImg\(img\).*?</script>', '', page, flags=re.S)
        page = page.replace('</head>', style + loader + '</head>', 1)
        page = re.sub(r'(<body\b[^>]*>)', lambda match: match[0] + navigation, page, count=1)
        # These exports used checkout-relative paths and retried several missing URLs per image.
        page = re.sub(r'(?:\.\./)+images/', 'https://img.handraw-style.com/images/', page)
        # No remote image URL is assigned to src until it reaches the visible queue.
        page = re.sub(r'<img\b[^>]*>', lambda match: re.sub(r'(?<![\w-])src=("[^"]+"|\x27[^\x27]+\x27)', lambda attr: f'src="{PLACEHOLDER}" data-hw-src={attr[1]}', match[0]), page)
        page = re.sub(r'\(cardImg\s*&&\s*cardImg\.src\)\s*\?\s*cardImg\.src', '(cardImg && cardImg.dataset.hwSrc) ? cardImg.dataset.hwSrc', page)
        page = re.sub(r'preview\.src\s*=\s*([^;]+);', r'window.HandrawImages.set(preview, \1);', page)
        if source.name == 'index.html':
            page = page.replace("localStorage.getItem('handdraw_gallery_size')||'1x'", "localStorage.getItem('handdraw_gallery_size')||'3x'")
        page = re.sub(r'href="((?:index|layouts|colors|assets|tutorials|characters)\.html)(?:\?[^"#]*)?(#[^"]*)?"',
                      lambda match: f'href="{match[1]}?v={revision}{match[2] or ""}"', page)
        (gallery / source.name).write_text(page, encoding='utf-8')
    for path in [target, assets, gallery, *target.rglob('*')]:
        path.chmod(0o755 if path.is_dir() else 0o644)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plugin', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('static_root', type=Path)
    args = parser.parse_args()
    build(args.plugin, args.target, args.static_root)
