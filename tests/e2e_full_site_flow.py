"""End-to-end flow check for the running local 2.0 site.

Exercises the real HTTP surface of a running server (default 127.0.0.1:3080)
across account, catalog, studio, forum, wallet and admin paths, and reports a
pass/fail line per flow. Intended for manual acceptance against a demo-mode
instance; it is not a replacement for the isolated unit suites.

Usage:
    python tests/e2e_full_site_flow.py [--base http://127.0.0.1:3080]
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request

RESULTS: list[tuple[str, bool, str]] = []


class Client:
    def __init__(self, base: str, origin: str = "") -> None:
        self.base = base.rstrip("/")
        self.origin = origin or self.base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method: str, path: str, body=None, timeout: int = 60):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method.upper() in ("POST", "PUT", "DELETE"):
            headers["Origin"] = self.origin
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, _maybe_json(raw)
        except urllib.error.HTTPError as err:
            return err.code, _maybe_json(err.read())

    def login(self, account: str, password: str) -> bool:
        status, _ = self.request("POST", "/api/auth/login", {"account": account, "password": password})
        return status == 200


def _maybe_json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {"_raw_len": len(raw)}


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:3080")
    parser.add_argument("--admin", default="yang0")
    parser.add_argument("--password", default="handraw123")
    parser.add_argument("--creator", default="su_editorial")
    args = parser.parse_args()
    base = args.base

    print("\n== 1. 访客与公开内容 ==")
    guest = Client(base)
    st, health = guest.request("GET", "/api/health")
    check("健康检查", st == 200 and health.get("ok") is True, f"HTTP {st}")
    st, boot = guest.request("GET", "/api/boot")
    ok_boot = st == 200 and boot.get("serverBacked") and not boot.get("loggedIn")
    check("访客启动载荷", ok_boot, f"HTTP {st} serverBacked={boot.get('serverBacked')}")
    check("公开作品可见", len(boot.get("works") or []) > 0, f"{len(boot.get('works') or [])} 件")
    check("公开帖子可见", len(boot.get("topics") or []) > 0, f"{len(boot.get('topics') or [])} 帖")
    check("目录资源计数", bool(boot.get("assetCounts")), f"{len(boot.get('assetCounts') or {})} 类")
    st, _ = guest.request("GET", "/data/catalog.json")
    check("画风图型目录", st == 200, f"HTTP {st}")
    st, _ = guest.request("GET", "/data/options.json")
    check("创作台选项", st == 200, f"HTTP {st}")

    print("\n== 2. 权限边界 ==")
    st, _ = guest.request("GET", "/api/admin/users")
    check("访客不可读后台用户", st == 401, f"HTTP {st}")
    st, _ = guest.request("GET", "/api/studio/tasks?id=unknown")
    check("访客不可查任务", st == 401, f"HTTP {st}")
    st, _ = guest.request("GET", "/api/notifications")
    check("访客不可读通知", st == 401, f"HTTP {st}")
    st, _ = guest.request("POST", "/api/works", {"title": "x"})
    check("访客不可发布作品", st == 401, f"HTTP {st}")
    st, _ = guest.request("GET", "/uploads/../backend/server.py")
    check("上传路径穿越被拦截", st == 404, f"HTTP {st}")

    print("\n== 3. 登录与账号 ==")
    admin = Client(base)
    check("管理员登录", admin.login(args.admin, args.password))
    st, boot_admin = admin.request("GET", "/api/boot")
    check("登录态识别", boot_admin.get("loggedIn") is True and boot_admin["user"]["username"] == args.admin)
    check("钱包额度存在", isinstance(boot_admin.get("credits"), int) and isinstance(boot_admin.get("freeQuotaRemaining"), int),
          f"积分 {boot_admin.get('credits')} 免费额度 {boot_admin.get('freeQuotaRemaining')}")
    st, acct = admin.request("GET", "/api/account/status")
    check("账号状态接口", st == 200 and "emailVerified" in acct, f"HTTP {st}")
    st, notif = admin.request("GET", "/api/notifications")
    check("通知中心可读", st == 200 and "items" in notif, f"{notif.get('unread')} 未读")
    st, perms = admin.request("GET", "/api/admin/permissions")
    check("权限档案", st == 200 and perms.get("profile", {}).get("effectiveRole") == "admin",
          f"role={perms.get('profile', {}).get('effectiveRole')}")

    print("\n== 4. 主站互动 ==")
    works = boot_admin.get("works") or []
    target_work = next((w for w in works if w["author"] != args.admin), works[0] if works else None)
    if target_work:
        wid = target_work["id"]
        st, r = admin.request("POST", f"/api/works/{wid}/comments", {"text": "端到端流程验证评论"})
        check("作品评论", st == 200, f"HTTP {st}")
        st, r = admin.request("POST", "/api/interactions/cheer", {"targetId": wid, "targetType": "work"})
        check("作品鼓励", st == 200, f"HTTP {st} {str(r.get('error') or '')[:40]}")
        st, r = admin.request("POST", "/api/collections/toggle", {"bucket": "works", "id": wid})
        check("收藏操作", st == 200, f"HTTP {st} {str(r.get('error') or '')[:40]}")
    else:
        check("作品评论", False, "无可用作品")

    print("\n== 5. 创作台与生成 ==")
    st, cfg = admin.request("GET", "/api/studio/config")
    check("创作台配置", st == 200, f"liveEnabled={cfg.get('liveImageEnabled')} demo={cfg.get('demoMode')}")
    st, ws = admin.request("GET", "/api/studio/workspace")
    check("创作台工作区", st == 200, f"HTTP {st}")
    st, hist = admin.request("GET", "/api/studio/history")
    check("生成历史", st == 200, f"HTTP {st}")
    st, gen = admin.request("POST", "/api/studio/generate",
                            {"prompt": "端到端验收：手绘纸张质感的小房子", "ratio": "3:4"},
                            timeout=200)
    live_ok = st == 200 and bool(gen.get("genId"))
    check("真实生图提交", live_ok, f"HTTP {st} task={gen.get('taskId')} cost={gen.get('costType')}")
    if live_ok:
        tid = gen.get("taskId") or ""
        final = ""
        images: list = []
        for _ in range(30):
            st, tr = admin.request("GET", f"/api/studio/tasks?id={tid}")
            final = tr.get("status") or ""
            images = tr.get("images") or []
            if final in ("success", "failed", "refunded"):
                break
            time.sleep(6)
        check("生图任务完成", final == "success", f"status={final} images={len(images)}")
        if images:
            st, _ = admin.request("GET", images[0])
            check("生成图片可读（所有者）", st == 200, f"HTTP {st}")
            st, _ = guest.request("GET", images[0])
            check("生成图片对访客隐藏", st == 404, f"HTTP {st}")

    print("\n== 6. 论坛 ==")
    st, topics = admin.request("GET", "/api/boot")
    boards = topics.get("forumBoards") or []
    check("板块列表", bool(boards), f"{len(boards)} 个板块")
    st, pub = admin.request("POST", "/api/forum/topics",
                            {"title": "端到端验收测试帖：流程是否通畅",
                             "body": "这是一条端到端流程验证帖，用于确认发帖、回复与治理链路。",
                             "category": "tuning"})
    check("发布论坛帖", st == 200 and bool(pub.get("topicId")), f"HTTP {st} {str(pub.get('error') or '')[:50]}")
    tid_new = pub.get("topicId")
    if tid_new:
        st, rep = admin.request("POST", f"/api/forum/topics/{tid_new}/replies", {"text": "端到端回复验证"})
        check("回复论坛帖", st == 200, f"HTTP {st}")
        st, det = admin.request("GET", f"/api/forum/topics/{tid_new}")
        check("帖子详情可读", st == 200, f"HTTP {st}")
        st, ed = admin.request("GET", f"/api/content/topics/{tid_new}/edit")
        check("作者可打开编辑", st == 200, f"HTTP {st}")
        if st == 200:
            st, edr = admin.request("POST", f"/api/content/topics/{tid_new}/edit",
                                    {"title": "端到端验收测试帖（已编辑）", "body": "编辑后的正文内容。"})
            check("作者可保存编辑", st == 200, f"HTTP {st}")
        st, mod = admin.request("POST", "/api/forum/moderate", {"topicId": tid_new, "op": "feature", "reason": "验收"})
        check("版主加精", st == 200, f"HTTP {st}")

    print("\n== 7. 钱包与奖励 ==")
    st, wallet = admin.request("GET", "/api/wallet")
    check("钱包接口", st == 200, f"HTTP {st}")
    st, ck = admin.request("POST", "/api/wallet/checkin", {})
    already = st == 400 and "已完成" in str(ck.get("error") or "")
    check("每日签到", st == 200 or already,
          f"HTTP {st} {str(ck.get('error') or ck.get('message') or '已签到')[:30]}")
    st, rc = admin.request("POST", "/api/wallet/recharge", {})
    check("充值未接入时明确禁用", st == 503 and rc.get("code") == "payment_disabled",
          f"HTTP {st} code={rc.get('code')}")

    print("\n== 8. 内容生产闭环 ==")
    stamp = int(time.time())
    newbie = Client(base)
    st, reg = newbie.request("POST", "/api/auth/register", {
        "username": f"e2e_user_{stamp}",
        "password": "e2eTest12345",
        "email": f"e2e_{stamp}@example.test",
        "displayName": "端到端新用户",
    })
    check("注册新账号", st == 200 and bool(reg.get("token")), f"HTTP {st} {str(reg.get('error') or '')[:40]}")
    st, nboot = newbie.request("GET", "/api/boot")
    check("新账号登录态", nboot.get("loggedIn") is True, f"user={nboot.get('user', {}).get('username')}")

    st, up = newbie.request("POST", "/api/uploads", {
        "dataUrl": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
        "name": "端到端上传",
    })
    upload_url = up.get("url") or ""
    check("上传图片", st == 200 and bool(upload_url), f"HTTP {st}")
    if upload_url:
        st, _ = newbie.request("GET", upload_url)
        check("上传者可读自己的图", st == 200, f"HTTP {st}")
        st, _ = guest.request("GET", upload_url)
        check("上传图对访客隐藏", st == 404, f"HTTP {st}")

    st, pubwork = newbie.request("POST", "/api/works", {
        "title": "端到端验收作品：手绘小风景",
        "prompt": "hand drawn paper texture landscape, pencil lines",
        "image": upload_url or "/images/individual/FA/FA-001.webp",
        "images": [upload_url or "/images/individual/FA/FA-001.webp"],
        "styles": ["FA-001"],
    })
    new_work = pubwork.get("workId") or pubwork.get("id") or ""
    check("发布作品", st == 200 and bool(new_work), f"HTTP {st} {str(pubwork.get('error') or '')[:50]}")
    if new_work:
        st, edit = newbie.request("GET", f"/api/content/works/{new_work}/edit")
        check("作品编辑入口", st == 200, f"HTTP {st}")
        st, editr = newbie.request("POST", f"/api/content/works/{new_work}/edit", {
            "title": "端到端验收作品（已编辑）",
            "prompt": "hand drawn paper texture landscape, edited",
        })
        check("作品编辑保存", st == 200, f"HTTP {st}")

    st, comm = newbie.request("POST", "/api/catalog/community", {
        "kind": "style",
        "name": f"端到端共创画风{stamp}",
        "description": "验收用共创画风说明",
        "image": "/images/individual/FA/FA-002.webp",
    })
    check("社区画风投稿", st == 200, f"HTTP {st} {str(comm.get('error') or '')[:50]}")

    print("\n== 9. 经济闭环 ==")
    st, tip = admin.request("POST", "/api/interactions/tip", {"targetType": "work", "targetId": wid, "amount": 2})
    check("积分打赏", st == 200, f"HTTP {st} {str(tip.get('error') or '')[:40]}")
    paid_work = next((w for w in works if int(w.get("price") or 0) > 0), None)
    if paid_work:
        st, unl = admin.request("POST", "/api/unlocks",
                                {"targetType": "work", "targetId": paid_work["id"]})
        check("付费解锁", st == 200, f"HTTP {st} {str(unl.get('error') or '')[:40]}")
    else:
        check("付费解锁", True, "无付费作品可解锁（跳过）")
    st, rep = admin.request("POST", "/api/reports", {
        "targetType": "work", "targetId": wid, "reason": "端到端验收举报（自动提交）",
    })
    check("提交举报", st == 200, f"HTTP {st} {str(rep.get('error') or '')[:40]}")

    print("\n== 10. 悬赏闭环 ==")
    st, bounty = newbie.request("POST", "/api/forum/topics", {
        "title": "端到端悬赏验收：求一个手绘封面方案",
        "body": "悬赏帖正文，用于验证托管、回答与采纳链路。",
        "category": "tuning",
        "mode": "bounty",
        "bounty": 5,
    })
    btid = bounty.get("topicId") or ""
    check("发布悬赏帖", st == 200 and bool(btid), f"HTTP {st} {str(bounty.get('error') or '')[:50]}")
    if btid:
        st, brep = admin.request("POST", f"/api/forum/topics/{btid}/replies", {"text": "端到端悬赏回答"})
        check("悬赏帖回复", st == 200, f"HTTP {st}")
        rid = brep.get("replyId") or brep.get("id") or ""
        if rid:
            st, acc = newbie.request("POST", f"/api/forum/topics/{btid}/accept-bounty", {"replyId": rid})
            check("采纳悬赏回答", st == 200, f"HTTP {st} {str(acc.get('error') or '')[:40]}")

    print("\n== 11. 管理后台 ==")
    for path, label in (
        ("/api/admin/dashboard", "数据总览"),
        ("/api/admin/users", "用户管理"),
        ("/api/admin/works", "作品管理"),
        ("/api/admin/topics", "帖子管理"),
        ("/api/admin/reports", "举报列表"),
        ("/api/admin/generations", "生成任务"),
        ("/api/admin/audit-logs", "审计日志"),
        ("/api/admin/settings", "站点设置"),
    ):
        st, data = admin.request("GET", path)
        check(f"后台 {label}", st == 200, f"HTTP {st}")

    print("\n== 12. 多角色边界 ==")
    creator = Client(base)
    if creator.login(args.creator, args.password):
        st, _ = creator.request("GET", "/api/admin/users")
        check("创作者被挡在后台用户页外", st == 403, f"HTTP {st}")
        st, cb = creator.request("GET", "/api/boot")
        check("创作者登录态", cb.get("loggedIn") is True, f"user={cb.get('user', {}).get('username')}")
    else:
        check("创作者登录", False, "无法登录")

    print("\n== 13. SEO 与静态资源 ==")
    for path in ("/robots.txt", "/sitemap.xml"):
        st, _ = guest.request("GET", path)
        check(f"{path}", st == 200, f"HTTP {st}")
    st, _ = guest.request("GET", "/")
    check("首页 HTML", st == 200, f"HTTP {st}")

    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)}，失败 {len(failed)}")
    if failed:
        print("\n失败项：")
        for name, _, detail in failed:
            print(f"  - {name} — {detail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
