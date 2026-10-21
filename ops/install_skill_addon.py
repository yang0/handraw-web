"""Install the portable integration without publishing or rewriting the official resource library."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = '<script src="personal-library.js" defer></script>'


def install(skill_root: Path):
    skill_root = skill_root.resolve()
    if not (skill_root / "SKILL.md").is_file():
        raise ValueError("Target must be a handraw-style Skill checkout")
    backup = ROOT / ".local" / "skill-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup.mkdir(parents=True, exist_ok=True)
    receipts = []

    def write(relative, text):
        target = skill_root / relative
        if target.is_file():
            prior = backup / relative
            prior.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, prior)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        receipts.append({"path": relative, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})

    addon = ROOT / "skill-addon"
    write("skills/personal-library/SKILL.md", (addon / "SKILL.md").read_text(encoding="utf-8"))
    client = (addon / "scripts/personal_library.py").read_text(encoding="utf-8")
    # The same complete client remains portable when distributed with the public Skill.
    client = client.replace("def main():\n", "def main():\n    os.environ.setdefault('HANDRAW_SKILL_ROOT', str(Path(__file__).resolve().parents[3]))\n")
    write("skills/personal-library/scripts/personal_library.py", client)
    wrapper = 'import runpy\nfrom pathlib import Path\nrunpy.run_path(str(Path(__file__).resolve().parents[1] / "skills/personal-library/scripts/personal_library.py"), run_name="__main__")\n'
    write("scripts/personal_library.py", wrapper)
    gallery = "skills/handdraw-style-prompter/gallery"
    write(f"{gallery}/personal-library.js", (addon / "personal_gallery.js").read_text(encoding="utf-8"))
    for filename in ("index.html", "layouts.html"):
        relative = f"{gallery}/{filename}"
        text = (skill_root / relative).read_text(encoding="utf-8")
        if MARKER not in text:
            write(relative, text.replace("</body>", MARKER + "\n</body>"))
    for filename, expression in (("build_library.py", "gallery_html(styles)"), ("build_layout_gallery.py", "gallery_html(layouts)")):
        relative = "skills/handdraw-style-prompter/scripts/" + filename
        text = (skill_root / relative).read_text(encoding="utf-8")
        replacement = expression + '.replace("</body>", \'<script src="personal-library.js" defer></script></body>\')'
        if 'src="personal-library.js"' not in text:
            text = text.replace(f"GALLERY.write_text({expression}, encoding=\"utf-8\")", f"GALLERY.write_text({replacement}, encoding=\"utf-8\")")
            write(relative, text)
    relative = "SKILL.md"
    text = (skill_root / relative).read_text(encoding="utf-8")
    if "## Personal resources and community collections" not in text:
        text += "\n\n## Personal resources and community collections\n\nWhen the user asks for 我的画风、我的图型、我的收藏、同步收藏、个人画风/图型 or importing a community resource package, read [personal-library](skills/personal-library/SKILL.md). Official entries remain unchanged; user-created and community-acquired entries live in the separate user library. Never upload personal resources without an explicit sharing request.\n"
        write(relative, text)
    relative = ".gitignore"
    text = (skill_root / relative).read_text(encoding="utf-8")
    if "/.handraw-personal/" not in text:
        write(relative, text + "\n# Private personal-library gallery mirror; never deploy\n/.handraw-personal/\n")
    mirror = skill_root / ".handraw-personal/library.js"
    if not mirror.exists():
        write(".handraw-personal/library.js", 'window.HANDRAW_PERSONAL_LIBRARY={"schema_version":1,"resources":[]};\n')
    (backup / "receipt.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(backup), "updated": receipts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, required=True)
    install(parser.parse_args().skill_root)
