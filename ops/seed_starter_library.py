"""Seed a realistic starter library: creators, works and their discussions.

This is *not* the demo fixture (``backend/seed.py``) and it is not the
fabricated cold-start registry.  Every work it creates points at a real style
image that ships in ``images/``, carries a real prompt, and publishes through
the same path a human would use — so the counters start at zero and stay
honest.

Usage:
    python -X utf8 ops/seed_starter_library.py --db .local/handraw_v2.db
    python -X utf8 ops/seed_starter_library.py --db .local/handraw_v2.db --apply
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _random_password() -> str:
    """A per-run random password; never a shared constant.

    Starter accounts exist only to give the square something real to show.  A
    hard-coded password would let anyone sign in as another "creator", so each
    account gets its own secret and the script tells the operator where it was
    written.
    """
    return "hws-starter-" + secrets.token_urlsafe(18)

# Each entry: (username, display name, works)
# Works reuse real style codes so the style detail pages show genuine usage.
CREATORS: list[tuple[str, str, list[dict]]] = [
    (
        "linnan",
        "林南",
        [
            {
                "title": "梅雨天里的一碗面",
                "style": "FE-012",
                "layout": "SC-021",
                "group": "美食",
                "prompt": "手绘风插画，雨中街角面馆，热气腾腾的一碗汤面，暖色灯光，纸张纹理，留白构图，社论插画感",
                "notes": "想做一篇关于城市小店的图文，用这张当开头。",
            },
            {
                "title": "通勤路上的三种表情",
                "style": "FA-013",
                "layout": "SC-021",
                "group": "职场",
                "prompt": "粗黑轮廓扁平色块，地铁车厢里三个人物，冷面幽默，互联网生活讽刺，白底留白",
                "notes": "试了三次才把表情拉开，关键是把肩胯方向做区分。",
            },
        ],
    ),
    (
        "chenmo",
        "陈默",
        [
            {
                "title": "旧书店的下午四点",
                "style": "FB-028",
                "layout": "SC-001",
                "group": "日常",
                "prompt": "柔和铅笔线稿，旧书店木质书架，斜射的午后光线，颗粒纸感，暖褐色调，安静叙事",
                "notes": "这本是做绘本时的一页，单独拿出来当情绪参考。",
            },
            {
                "title": "关于失眠的一页绘本",
                "style": "FB-041",
                "layout": "SC-001",
                "group": "日常",
                "prompt": "克制的水彩晕染，深夜房间，一个人盯着天花板的俯视构图，冷蓝与暖黄对比，绘本叙事",
                "notes": "",
            },
        ],
    ),
    (
        "yuzi_art",
        "柚子",
        [
            {
                "title": "桂花乌龙的海报尝试",
                "style": "FE-030",
                "layout": "SC-021",
                "group": "商业",
                "prompt": "新国风插画，桂花枝叶与茶汤特写，低饱和暖金配色，宣纸质感，适合海报主视觉",
                "notes": "给茶馆做的小红书封面，最后这版留白最多、效果最好。",
            },
            {
                "title": "中秋礼盒的包装草图",
                "style": "FE-005",
                "layout": "EC-002",
                "group": "商业",
                "prompt": "传统工艺质感插画，月饼礼盒平铺俯拍，金箔点缀，细线勾勒纹样，深红与暗金",
                "notes": "",
            },
        ],
    ),
    (
        "helan",
        "何岚",
        [
            {
                "title": "给朋友做的生日插画",
                "style": "FD-016",
                "layout": "SC-021",
                "group": "日常",
                "prompt": "日本当代插画风，女孩抱着蛋糕坐在窗边，柔和粉彩色，细黑线，大面积留白",
                "notes": "参照这个画风的笔触质感，人物比例故意做得不写实。",
            },
            {
                "title": "雨后玻璃窗的特写",
                "style": "FI-008",
                "layout": "SC-001",
                "group": "摄影",
                "prompt": "写实摄影风格，雨滴附着玻璃窗，背景霓虹虚化，浅景深，冷色调，电影感打光",
                "notes": "",
            },
        ],
    ),
    (
        "tangyuan",
        "汤圆",
        [
            {
                "title": "卡通形象的第一版设定",
                "style": "FG-004",
                "layout": "EC-002",
                "group": "IP",
                "prompt": "动漫赛璐璐风格，圆脸角色正面站姿，简洁配色，粗描边，表情自然，白底",
                "notes": "还在迭代，先记录第一版。",
            },
            {
                "title": "猫在键盘上睡着了",
                "style": "FF-006",
                "layout": "SC-021",
                "group": "日常",
                "prompt": "3D黏土质感，橘猫趴在笔记本键盘上睡觉，柔和打光，浅景深，可爱笨拙感",
                "notes": "",
            },
        ],
    ),
]


def _resolve_image(style_code: str) -> str:
    """Return the shipped style image path, or empty when it is absent."""
    path = Path(__file__).resolve().parent.parent / "images" / "individual" / style_code[:2] / f"{style_code}.webp"
    if path.is_file():
        return f"/images/individual/{style_code[:2]}/{style_code}.webp"
    return ""


def build_plan(db) -> dict:
    """Return what would be created, without writing anything."""
    from backend.resource_discussions import resolve_resource

    conn = db.get_conn()
    plan = {"creators": [], "works": [], "skipped": []}
    for username, display, works in CREATORS:
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        plan["creators"].append({"username": username, "displayName": display, "exists": bool(exists)})
        for work in works:
            image = _resolve_image(work["style"])
            if not image:
                plan["skipped"].append({"title": work["title"], "reason": f"缺少画风图 {work['style']}"})
                continue
            if not resolve_resource(conn, "style", work["style"]):
                plan["skipped"].append({"title": work["title"], "reason": f"画风 {work['style']} 未收录"})
                continue
            layout = work.get("layout") or ""
            if layout and not resolve_resource(conn, "layout", layout):
                layout = ""
            plan["works"].append(
                {
                    "owner": username,
                    "title": work["title"],
                    "prompt": work["prompt"],
                    "notes": work["notes"],
                    "images": [image],
                    "styles": [work["style"]],
                    "layout": layout,
                    "requestId": f"starter-{work['style']}-{username}",
                }
            )
    return plan


def apply_plan(db, plan: dict) -> dict:
    from backend.services import publish_user_work, register_user

    created_works = 0
    created_users = 0
    credentials: list[dict] = []
    conn = db.get_conn()
    for creator in plan["creators"]:
        # Re-check rather than trusting the plan: a plan built earlier may be
        # replayed after an interrupted run.
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (creator["username"],)).fetchone():
            continue
        password = _random_password()
        register_user(db, creator["username"], password, display_name=creator["displayName"])
        credentials.append({"username": creator["username"], "password": password})
        created_users += 1

    for work in plan["works"]:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (work["owner"],)).fetchone()
        if not row:
            continue
        try:
            publish_user_work(db, dict(row), work)
            created_works += 1
        except Exception as exc:  # noqa: BLE001 - report and continue seeding
            plan["skipped"].append({"title": work["title"], "reason": str(exc)[:120]})
    return {"users": created_users, "works": created_works, "credentials": credentials}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a starter library of real works.")
    parser.add_argument("--db", required=True, help="Path to the SQLite database")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args(argv)

    from backend.db import Database

    db_path = Path(args.db).resolve()
    db = Database(db_path)
    db.migrate()
    try:
        plan = build_plan(db)
        print(f"计划创建账号 {sum(1 for c in plan['creators'] if not c['exists'])} 个，作品 {len(plan['works'])} 件")
        for work in plan["works"]:
            print(f"  {work['owner']}: {work['title']}  [{work['styles'][0]} / {work['layout'] or '无图型'}]")
        if plan["skipped"]:
            print("跳过：")
            for item in plan["skipped"]:
                print(f"  {item['title']}：{item['reason']}")
        if not args.apply:
            print("干跑完成，未写入。加 --apply 执行。")
            return 0
        result = apply_plan(db, plan)
        print(f"已创建账号 {result['users']} 个，作品 {result['works']} 件。")
        if result.get("credentials"):
            # Written to an ignored path, never printed: a password in scrollback
            # or CI logs is a leaked password.
            out = Path(args.db).resolve().parent / "starter_credentials.json"
            out.write_text(
                json.dumps(result["credentials"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"账号凭据已写入 {out}（请妥善保管并在首次登录后修改密码）")
        return 0
    finally:
        db.get_conn().close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
