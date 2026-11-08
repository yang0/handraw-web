"""Export newly added official assets from Handraw Web to Skill repository format."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from backend.config import get_uploads_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--db", type=Path, help="Path to isolated SQLite database")
    database.add_argument("--pg-dsn-env", type=str, help="Environment variable holding read-only PG17 DSN (never pass a secret on CLI)")
    parser.add_argument("--skill-root", type=Path, required=True, help="Path to <Skill>/skills/handdraw-style-prompter")
    parser.add_argument("--out", type=Path, default=Path(".local/export-official"), help="New empty output directory")
    args = parser.parse_args()

    db_path = args.db.resolve() if args.db else None
    if db_path is not None and not db_path.is_file():
        print("Error: SQLite 数据库文件不存在", file=sys.stderr)
        sys.exit(1)
    if args.pg_dsn_env:
        import re
        if not re.fullmatch(r"HANDRAW_[A-Z][A-Z0-9_]{0,80}", args.pg_dsn_env) or not os.environ.get(args.pg_dsn_env):
            print("Error: 需提供受控的 PG 只读连接环境变量", file=sys.stderr)
            sys.exit(1)

    skill_root = args.skill_root.resolve()
    if not skill_root.is_dir():
        print(f"Error: Skill 根目录不存在: {skill_root}", file=sys.stderr)
        sys.exit(1)

    skill_styles_file = skill_root / "references/styles.json"
    skill_layouts_file = skill_root / "references/layouts.json"
    if not skill_styles_file.is_file() or not skill_layouts_file.is_file():
        print(f"Error: Skill references 文件不存在: {skill_styles_file} 或 {skill_layouts_file}", file=sys.stderr)
        sys.exit(1)

    # 1. Read website-approved official assets from DB. Do NOT create tables,
    # migrate schemas or issue a write. PG requires a separate read-only role.
    query = ("SELECT * FROM catalog_assets WHERE source_type = 'official' "
             "AND status = 'published' ORDER BY code ASC")
    if db_path is not None:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            official_assets = conn.execute(query).fetchall()
        finally:
            conn.close()
    else:
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(os.environ[args.pg_dsn_env], row_factory=dict_row,
                                 autocommit=False, connect_timeout=5) as conn:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                official_assets = conn.execute(query).fetchall()
        except Exception:
            # Never render the DSN or raw server errors to public CI logs.
            print("Error: PostgreSQL 只读官方目录导出失败；检查数据库权限与连接", file=sys.stderr)
            sys.exit(2)

    if not official_assets:
        print("未找到 source_type='official' 的官方新增资产。")
        sys.exit(0)

    # 2. Collision check (同号防护)
    skill_styles = json.loads(skill_styles_file.read_text(encoding="utf-8"))
    skill_layouts = json.loads(skill_layouts_file.read_text(encoding="utf-8"))
    skill_style_map = {
        str(s.get("number") or s.get("id") or "").strip().upper(): s
        for s in skill_styles
        if s.get("number") or s.get("id")
    }
    skill_layout_map = {
        str(l.get("id") or l.get("number") or "").strip().upper(): l
        for l in skill_layouts
        if l.get("id") or l.get("number")
    }

    conflicts: list[tuple[str, str, str]] = []
    for row in official_assets:
        code = str(row["code"]).strip().upper()
        kind = str(row["kind"]).strip().lower()
        site_name = str(row["name"]).strip()
        if kind == "style" and code in skill_style_map:
            skill_item = skill_style_map[code]
            skill_name = skill_item.get("generation_name") or skill_item.get("name") or ""
            conflicts.append((code, site_name, skill_name))
        elif kind == "layout" and code in skill_layout_map:
            skill_item = skill_layout_map[code]
            skill_name = skill_item.get("name") or ""
            conflicts.append((code, site_name, skill_name))

    if conflicts:
        print("错误：待导出的官方资产与 Skill 仓库存在同号冲突！", file=sys.stderr)
        for code, site_name, skill_name in conflicts:
            print(f"  - 编号: {code} | 网站名称: '{site_name}' | Skill 现有名称: '{skill_name}'", file=sys.stderr)
        sys.exit(2)

    # 3. Check catalog.json overlap
    catalog_path = REPO_ROOT / "plugin/content/catalog.json"
    catalog_codes: set[str] = set()
    if catalog_path.is_file():
        try:
            cat_data = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog_codes = {str(r.get("id")).strip().upper() for r in cat_data.get("resources", [])}
        except Exception:
            pass

    already_in_catalog = [str(r["code"]).strip().upper() for r in official_assets if str(r["code"]).strip().upper() in catalog_codes]
    if already_in_catalog:
        print(f"提示：以下编号已存在于当前 catalog.json 中: {already_in_catalog}")

    # 4. Prepare export data
    exported_styles: list[dict[str, Any]] = []
    exported_layouts: list[dict[str, Any]] = []
    layout_prompts: dict[str, str] = {}
    # A release artifact must not silently retain assets from an older export.
    # In particular, a newly hidden/unapproved resource must never survive in
    # an existing directory and be mistakenly published to Skill.
    if args.out.is_symlink() or (args.out.exists() and
                                   (not args.out.is_dir() or any(args.out.iterdir()))):
        print("拒绝导出：目标必须是新的空目录，禁止覆盖旧发布包", file=sys.stderr)
        sys.exit(2)
    out_dir = args.out.resolve()

    for row in official_assets:
        code = str(row["code"]).strip().upper()
        kind = str(row["kind"]).strip().lower()
        cost = int(row["unlock_cost"] or 0)
        desc = str(row["description"] or "").strip()
        definition = str(row["definition"] or "").strip()

        if kind == "style":
            if cost > 0:
                exported_styles.append({
                    "number": code,
                    "group": row["group_name"] or "",
                    "reference": "",
                    "generation_name": row["name"],
                    "traits": "",
                })
            else:
                exported_styles.append({
                    "number": code,
                    "group": row["group_name"] or "",
                    "reference": "",
                    "generation_name": row["name"],
                    "traits": desc or definition,
                    "definition": definition,
                })
        elif kind == "layout":
            category = str(row["group_name"] or "infographic").strip()
            skill_img_path = f"../../../images/layouts/{category}/{code}.webp"
            keywords = [k.strip() for k in desc.split("、") if k.strip()]
            if not keywords:
                keywords = [row["name"]]

            entry: dict[str, Any] = {
                "id": code,
                "category": category,
                "name": row["name"],
                "image": skill_img_path,
                "keywords": keywords,
            }
            if cost <= 0:
                prompt_file = f"layouts/{code}.md"
                entry["prompt_file"] = prompt_file
                entry["definition"] = definition
                layout_prompts[f"{code}.md"] = definition
            exported_layouts.append(entry)

    # 5. Write files to out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "styles.json").write_text(
        json.dumps(exported_styles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "layouts.json").write_text(
        json.dumps(exported_layouts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if layout_prompts:
        layouts_dir = out_dir / "layouts"
        layouts_dir.mkdir(parents=True, exist_ok=True)
        for fname, ptext in layout_prompts.items():
            (layouts_dir / fname).write_text(ptext, encoding="utf-8")

    # 6. Copy local upload images
    images_dir = out_dir / "images"
    images_copied = 0
    uploads_dir = get_uploads_dir()
    for row in official_assets:
        img_url = str(row["image_url"] or "").strip()
        if img_url.startswith("/uploads/"):
            rel = img_url.removeprefix("/uploads/").split("?", 1)[0]
            fpath = uploads_dir / rel
            if fpath.is_file():
                ext = fpath.suffix or ".webp"
                code = str(row["code"]).strip().upper()
                kind = str(row["kind"]).strip().lower()
                if kind == "style":
                    series = code.split("-")[0]
                    dest = images_dir / "individual" / series / f"{code}{ext}"
                else:
                    cat_name = str(row["group_name"] or "infographics").strip()
                    dest = images_dir / "layouts" / cat_name / f"{code}{ext}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fpath, dest)
                images_copied += 1

    print(f"导出成功！已将 {len(official_assets)} 个官方资产片段导出至: {out_dir}")
    print(f"  - styles.json: {len(exported_styles)} 项")
    print(f"  - layouts.json: {len(exported_layouts)} 项")
    print(f"  - 图片文件: {images_copied} 个")


if __name__ == "__main__":
    main()
