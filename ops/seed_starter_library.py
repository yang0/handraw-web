"""Seed a starter library of real works.

This is *not* the demo fixture (``backend/seed.py``) and not the fabricated
cold-start registry.  It publishes through the same path a human would use, so
counters start at zero and stay honest.

**Provenance matters here.**  The images are the style gallery's own reference
art from the handraw-style package, which carries the original illustrators'
signatures.  They are therefore labelled as *style reference examples* — the
title and prompt describe what the picture actually shows, and the account name
says 官方示例.  Presenting them as a community member's own work would misstate
authorship.

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
    """A per-run random password; never a shared constant."""
    return "hws-starter-" + secrets.token_urlsafe(18)


# Each entry describes the *shipped reference image* it points at, so the title,
# the prompt and the picture agree.  ``EXAMPLE_MARK`` keeps the provenance
# visible wherever the work is listed.
EXAMPLE_MARK = "画风参考示例"

CREATORS: list[tuple[str, str, list[dict]]] = [
    (
        "linnan",
        "官方示例·社论线",
        [
            {
                "title": "抱冲浪板的男孩 · FA-013 画风参考",
                "style": "FA-013",
                "layout": "SC-021",
                "prompt": "粗黑轮廓、扁平色块、现代人物漫画。一个抱着黄色冲浪板的男孩，戴蓝色帽子，举手比出胜利手势，橙棕色皮肤与黑色卷发，纯白背景，只用少量暖色块点缀。",
                "notes": f"{EXAMPLE_MARK}：这是画风库 FA-013（Bold Flat Everyday Satire）的标准样图，用于展示该画风的线条粗细与色块处理，不是社区成员的作品。",
            },
            {
                "title": "旗袍女子与红日 · FE-012 画风参考",
                "style": "FE-012",
                "layout": "SC-021",
                "prompt": "新国风插画，侧脸盘发女子穿黑色高领旗袍，身后一轮朱红大圆日，左侧飞过一只白鹤，远处中式楼阁与凉亭，低饱和墨色与朱砂红对比，纸本质感。",
                "notes": f"{EXAMPLE_MARK}：画风库 FE-012 的标准样图，展示传统元素与现代编辑插画的结合方式。",
            },
        ],
    ),
    (
        "chenmo",
        "官方示例·绘本线",
        [
            {
                "title": "灯下画画的人与鸭子 · FB-028 画风参考",
                "style": "FB-028",
                "layout": "SC-001",
                "prompt": "水彩与铅笔混合的绘本插画。一个头发蓬乱的胡子男人坐在桌前笔记本前写字，桌上一只白色鸭子站在笔筒旁，背景是红色电话亭与书架，暖黄灯光，松散笔触与纸纹。",
                "notes": f"{EXAMPLE_MARK}：画风库 FB-028 的标准样图，展示水彩晕染与铅笔线条的叠加。",
            },
            {
                "title": "童话城堡里的两个老人 · FG-004 画风参考",
                "style": "FG-004",
                "layout": "EC-002",
                "prompt": "赛璐璐动画风格。石砌拱门前的两个卡通老人，一个宽脸大胡子穿浅绿制服戴军帽，一个瘦削戴白色尖帽挂单边眼镜，柔和阴影与清晰描边，复古动画质感。",
                "notes": f"{EXAMPLE_MARK}：画风库 FG-004 的标准样图，展示经典动画赛璐璐的描边与上色方式。",
            },
        ],
    ),
    (
        "yuzi_art",
        "官方示例·商业线",
        [
            {
                "title": "手帐涂鸦女孩 · FE-030 画风参考",
                "style": "FE-030",
                "layout": "SC-021",
                "prompt": "手帐本涂鸦风，短发丸子头女孩趴在地板上写东西，条纹短袖与牛仔裤，旁边是笔记簿、马克杯、盆栽和一只趴着的猫，四周散落手绘星星与 Happy Day 手写字，棕色细线与暖白纸色。",
                "notes": f"{EXAMPLE_MARK}：画风库 FE-030（Notebook Lifestyle Doodle）的标准样图，展示手帐式的轻涂鸦与手写字排版。",
            },
            {
                "title": "海边城墙上的猫与人 · FE-005 画风参考",
                "style": "FE-005",
                "layout": "EC-002",
                "prompt": "旅行水彩日记风。一个短发女孩背对镜头坐在海边石墙上，旁边蹲着一只黑猫，前方是湛蓝海面与白色游船，右侧沿海崖叠着橙顶白墙的小镇房屋，天空有薄云，笔触松弛透亮。",
                "notes": f"{EXAMPLE_MARK}：画风库 FE-005（旅行与季节 / 水彩日记风）的标准样图，展示旅行速写式的水彩层次。",
            },
        ],
    ),
    (
        "helan",
        "官方示例·插画线",
        [
            {
                "title": "街头滑板少年 · FD-016 画风参考",
                "style": "FD-016",
                "layout": "SC-021",
                "prompt": "现代都市少年插画，戴棒球帽的男生坐在滑板上，白卫衣配黑色宽松长裤与厚底运动鞋，身边放着黑色背包，背景是灰色楼宇与墙面涂鸦，冷灰主调、线稿清晰。",
                "notes": f"{EXAMPLE_MARK}：画风库 FD-016（Free-Line Urban Youth Comic）的标准样图，展示都市青年的线稿与配色处理。",
            },
            {
                "title": "白墙海边的人像 · FI-008 画风参考",
                "style": "FI-008",
                "layout": "SC-001",
                "prompt": "写实摄影。一位戴宽檐草帽与墨镜的女性坐在白色石阶上，米白色长裙垂落在墙边，身后是深蓝海面与远处岛屿，右侧有一株橄榄树，正午强光、清晰阴影与高饱和蓝白色调。",
                "notes": f"{EXAMPLE_MARK}：画风库 FI-008 的标准样图，展示写实摄影的光比与色彩处理。",
            },
        ],
    ),
    (
        "tangyuan",
        "官方示例·黏土线",
        [
            {
                "title": "街头的黏土西装男 · FF-006 画风参考",
                "style": "FF-006",
                "layout": "SC-021",
                "prompt": "3D 黏土定格动画质感。一个穿蓝色西装、白衬衫系黑领带的黏土男人站在路口，一只手拿外带咖啡杯，皱眉撇嘴表情夸张，身后是虚化的街景（黄色小车、红灯、消防栓、招牌），柔和棚拍打光与哑光黏土表面。",
                "notes": f"{EXAMPLE_MARK}：画风库 FF-006 的标准样图，展示黏土材质的表面质感与夸张造型。",
            },
            {
                "title": "溪边的小熊与小鸟 · FB-041 画风参考",
                "style": "FB-041",
                "layout": "SC-001",
                "prompt": "柔和绘本插画。一只毛茸茸的棕色小熊坐在溪边长满青苔的石头上，伸出一只爪子，掌心里停着一只小鸟，背景是逆光下的针叶林与流水，暖金色晨雾，颗粒纸感与柔焦。",
                "notes": f"{EXAMPLE_MARK}：画风库 FB-041 的标准样图，展示绘本式的柔光与毛绒质感。",
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
    parser = argparse.ArgumentParser(description="Seed a starter library of reference examples.")
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
            out = Path(args.db).resolve().parent / "starter_credentials.json"
            out.write_text(
                json.dumps(result["credentials"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"账号凭据已写入 {out}（请妥善保管并在首次登录后修改密码）")
        return 0
    finally:
        db.close_thread_conn()
        db.get_conn().close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
