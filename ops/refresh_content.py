"""Refresh the public resource snapshot from a checked-out official Skill."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = REPO_ROOT / "plugin/content"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from backend.skill_prompt import strip_bilingual_definition


def _read_skill_text(skill_dir: Path, rel_subpath: str, git_ref: str | None = None) -> str:
    target_file = skill_dir / rel_subpath
    if git_ref is not False:
        ref_to_use = git_ref
        if ref_to_use is None:
            try:
                # If this is the official handraw-style repo, verify commit ab79013 per spec
                v_res = subprocess.run(
                    ["git", "-C", str(skill_dir), "rev-parse", "--verify", "ab79013^{commit}"],
                    capture_output=True,
                    text=True,
                )
                if v_res.returncode == 0:
                    ref_to_use = "ab79013"
                else:
                    ref_to_use = "HEAD"
            except Exception:
                ref_to_use = "HEAD"

        try:
            res = subprocess.run(
                ["git", "-C", str(skill_dir), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            )
            git_root = Path(res.stdout.strip()).resolve()
            rel_to_git = target_file.resolve().relative_to(git_root).as_posix()
            show_res = subprocess.run(
                ["git", "-C", str(git_root), "show", f"{ref_to_use}:{rel_to_git}"],
                capture_output=True,
                encoding="utf-8",
                check=True,
            )
            return show_res.stdout
        except Exception:
            pass

    if target_file.is_file():
        return target_file.read_text(encoding="utf-8")
    return ""


def _read_skill_json(skill_dir: Path, rel_subpath: str, git_ref: str | None = None) -> Any:
    text = _read_skill_text(skill_dir, rel_subpath, git_ref=git_ref)
    if not text:
        return []
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill", type=Path, help="Path to skills/handdraw-style-prompter")
    parser.add_argument("--accept", nargs="*", default=[], help="List or comma-separated asset codes to accept")
    parser.add_argument("--db", type=Path, default=None, help="Path to SQLite database")
    parser.add_argument("--ref", type=str, default=None, help="Specific git ref to read from (defaults to ab79013/HEAD if in git)")
    parser.add_argument("--worktree", action="store_true", help="Read directly from working directory instead of git")
    args = parser.parse_args()

    git_ref = False if args.worktree else args.ref
    skill_dir = args.skill.resolve()

    styles = _read_skill_json(skill_dir, "references/styles.json", git_ref=git_ref)
    layouts = _read_skill_json(skill_dir, "references/layouts.json", git_ref=git_ref)
    colors = _read_skill_json(skill_dir, "references/colors.json", git_ref=git_ref)

    gallery_html = _read_skill_text(skill_dir, "gallery/index.html", git_ref=git_ref)
    legacy = dict(re.findall(r'data-number="([A-Z]+-\d+)"[^>]*data-legacy="(\d+)"', gallery_html))

    skill_resources = []
    for item in styles:
        number = item.get("number") or item.get("id") or ""
        if not number:
            continue
        gen_name = item.get("generation_name") or item.get("name") or ""
        traits = item.get("traits") or item.get("description") or ""
        ref_author = item.get("reference") or item.get("ref") or ""
        definition = f"#{number} {gen_name}。参考作者/风格名称：{ref_author}。核心风格特征：{traits}。"
        skill_resources.append({
            "id": number,
            "legacy": legacy.get(number, ""),
            "kind": "style",
            "name": gen_name,
            "group": item.get("group", ""),
            "description": traits if isinstance(traits, str) else json.dumps(traits, ensure_ascii=False),
            "definition": definition,
            "image": f"https://img.handraw-style.com/images/individual/{number.split('-')[0]}/{number}.webp",
        })

    for item in layouts:
        prompt_rel = f"references/{item['prompt_file']}" if item.get("prompt_file") else ""
        prompt_text = _read_skill_text(skill_dir, prompt_rel, git_ref=git_ref) if prompt_rel else (item.get("definition") or item.get("description") or "")
        image_url = str(item.get("image") or "").replace("../../../images/", "https://img.handraw-style.com/images/")
        keywords = item.get("keywords") or []
        desc = "、".join(keywords) if isinstance(keywords, list) else str(item.get("description") or "")
        skill_resources.append({
            "id": item.get("id") or item.get("number") or "",
            "kind": "layout",
            "name": item.get("name", ""),
            "group": item.get("category") or item.get("group", ""),
            "description": desc,
            "definition": strip_bilingual_definition(prompt_text) if prompt_text else "",
            "image": image_url,
        })

    for item in colors:
        image_url = item["image"].replace("../../../images/", "https://img.handraw-style.com/images/")
        skill_resources.append({
            "id": item["id"],
            "kind": "color",
            "name": item["name_zh"],
            "group": item["category_zh"],
            "description": item["quote_zh"],
            "definition": item["prompt_zh"],
            "image": image_url,
        })

    target_content_dir = CONTENT_DIR
    catalog_path = target_content_dir / "catalog.json"
    editorial_path = target_content_dir / "editorial.json"

    old_catalog: dict[str, Any] = {}
    if catalog_path.is_file():
        old_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    old_resources = old_catalog.get("resources", [])
    old_resources_by_id = {r["id"]: r for r in old_resources}

    # Build known codes
    known_codes = set(old_resources_by_id.keys())
    if args.accept:
        for item in args.accept:
            for code in re.split(r"[\s,]+", str(item).strip()):
                c = code.strip().upper()
                if c:
                    known_codes.add(c)

    db_official_codes: set[str] = set()
    if args.db and args.db.is_file():
        conn = sqlite3.connect(str(args.db))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT code FROM catalog_assets WHERE source_type = 'official'").fetchall()
            for r in rows:
                db_official_codes.add(str(r["code"]).strip().upper())
            known_codes.update(db_official_codes)
        finally:
            conn.close()

    # Direction locking check (锁方向)
    skill_codes = {item["id"] for item in skill_resources}
    unknown_codes = skill_codes - known_codes
    if unknown_codes:
        print(f"Error: Skill 仓库中出现新编号但未被放行: {sorted(unknown_codes)}", file=sys.stderr)
        print("如需收编请使用 --accept 参数放行，或指定 --db 读取数据库中已建编号。", file=sys.stderr)
        sys.exit(1)

    # Reconstruct resources list: preserve existing 534 entries unchanged, append new entries
    final_resources = []
    existing_modifications = []
    for item in skill_resources:
        cid = item["id"]
        if cid in old_resources_by_id:
            old_item = old_resources_by_id[cid]
            # Check for changes in existing entries
            diff_fields = []
            for k in ("name", "group", "description", "definition"):
                if old_item.get(k, "") != item.get(k, ""):
                    diff_fields.append((k, old_item.get(k, ""), item.get(k, "")))
            if diff_fields:
                existing_modifications.append((cid, diff_fields))
            # Keep existing entry unchanged to avoid polluting catalog with unapproved skill changes
            final_resources.append(old_item)
        else:
            final_resources.append(item)

    # Check editorial featured resources
    editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
    index = {item["id"]: item for item in final_resources}
    for item in editorial["featured"]:
        if item["id"] not in index:
            raise SystemExit(f'Featured resource is missing: {item["id"]}; no content was written.')
    for item in editorial["featured"]:
        item.update(index[item["id"]])
    for item in editorial.get("featured_layouts", []):
        item.update(index[item["id"]])

    counts = {
        "style": len([r for r in final_resources if r.get("kind") == "style"]),
        "layout": len([r for r in final_resources if r.get("kind") == "layout"]),
        "color": len([r for r in final_resources if r.get("kind") == "color"]),
    }
    editorial["counts"] = counts

    # Write files
    catalog_payload = {
        "version": 1,
        "source": "yang0/handraw-style official references",
        "counts": counts,
        "resources": final_resources,
    }
    catalog_path.write_text(json.dumps(catalog_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    editorial_path.write_text(json.dumps(editorial, ensure_ascii=False, indent=2), encoding="utf-8")

    # If --db was provided, update catalog_assets official -> official_override
    if args.db and args.db.is_file():
        conn = sqlite3.connect(str(args.db))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT code FROM catalog_assets WHERE source_type = 'official'").fetchall()
            converted = []
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for r in rows:
                code_val = str(r["code"]).strip().upper()
                if code_val in index:
                    conn.execute(
                        "UPDATE catalog_assets SET source_type = 'official_override', updated_at = ? WHERE code = ?",
                        (now_iso, code_val),
                    )
                    converted.append(code_val)
            conn.commit()
            if converted:
                print(f"已将同时存在于 catalog.json 的 {len(converted)} 个官方资产更新为 official_override: {converted}")
        finally:
            conn.close()

    print(f"Refreshed {len(final_resources)} official resources. Counts: styles={counts['style']}, layouts={counts['layout']}, colors={counts['color']}")
    if existing_modifications:
        print(f"检测到 Skill 仓库中存在 {len(existing_modifications)} 个已有条目发生改动（按规则保留原内容未提交）：")
        for cid, diffs in existing_modifications:
            diff_str = "; ".join([f"{f}: '{old[:20]}...' -> '{new[:20]}...'" for f, old, new in diffs])
            print(f"  - {cid}: {diff_str}")


if __name__ == "__main__":
    main()
