"""Account recovery, private notifications and owner content editing endpoints.

Mail credentials live in ignored private storage. Tokens are hashed, single-use,
expire quickly, and never appear in API responses or application logs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .config import WEB_ROOT, CONTENT_DIR
from .db import utc_now_iso
from .security import hash_password
from .services import ServiceError, record_audit_log


def mail_config() -> dict[str, Any]:
    path = Path(os.environ.get("HANDRAW_MAIL_CONFIG", str(WEB_ROOT / ".local" / "mail-service.json")))
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    for key in ("host", "username", "password", "sender"):
        value = os.environ.get("HANDRAW_SMTP_" + key.upper())
        if value is not None:
            cfg[key] = value
    cfg["port"] = int(os.environ.get("HANDRAW_SMTP_PORT", cfg.get("port", 587)))
    return cfg


def mail_ready() -> bool:
    cfg = mail_config()
    return bool(cfg.get("host") and cfg.get("sender"))


def send_account_mail(recipient: str, purpose: str, token: str) -> None:
    cfg = mail_config()
    if not cfg.get("host") or not cfg.get("sender"):
        raise ServiceError("邮件服务尚未配置，请联系管理员", status=503, code="mail_unavailable")
    base = str(os.environ.get("HANDRAW_PUBLIC_URL", "http://localhost:3080")).rstrip("/")
    view = "reset-password" if purpose == "password_reset" else "verify-email"
    url = base + "/?" + urlencode({"view": view, "token": token,
                                   "purpose": "change" if purpose == "email_change" else "verify"})
    action = {"password_reset": "重置密码", "verify_email": "验证邮箱",
              "email_change": "验证并绑定新邮箱"}.get(purpose, "验证邮箱")
    msg = EmailMessage()
    msg["From"] = str(cfg["sender"])
    msg["To"] = recipient
    msg["Subject"] = f"Handraw · {action}"
    msg.set_content(f"请通过以下链接{action}，链接 30 分钟内有效且仅能使用一次：\n\n{url}\n\n如果不是你发起的操作，请忽略此邮件。")
    try:
        factory = smtplib.SMTP_SSL if cfg.get("ssl") else smtplib.SMTP
        options = {"context": ssl.create_default_context()} if cfg.get("ssl") else {}
        with factory(str(cfg["host"]), int(cfg["port"]), timeout=15, **options) as smtp:
            if not cfg.get("ssl"):
                smtp.ehlo()
                if cfg.get("starttls", True):
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
            if cfg.get("username"):
                smtp.login(str(cfg["username"]), str(cfg.get("password") or ""))
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise ServiceError("邮件暂时无法发送，请稍后重试", status=503, code="mail_unavailable") from exc


def request_account_mail(db: Any, purpose: str, email: str, user: dict | None = None) -> dict:
    clean = parseaddr(email.strip())[1].lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean):
        raise ServiceError("请输入有效的注册邮箱")
    if not mail_ready():
        raise ServiceError("邮件服务尚未配置，请联系管理员", status=503, code="mail_unavailable")
    row = db.get_conn().execute("SELECT id,email,status FROM users WHERE lower(email)=?", (clean,)).fetchone()
    generic = {"ok": True, "message": "如果邮箱对应有效账号，将收到邮件，请检查收件箱。"}
    if not row or row["status"] != "active":
        return generic
    if purpose == "verify_email" and (not user or int(row["id"]) != int(user["id"])):
        raise ServiceError("只能验证当前账号的邮箱", status=403)
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db.transaction() as tx:
        last = tx.execute("SELECT created_at FROM account_action_tokens WHERE user_id=? AND purpose=? ORDER BY created_at DESC LIMIT 1", (row["id"], purpose)).fetchone()
        if last and now - int(last["created_at"]) < 60:
            raise ServiceError("操作过于频繁，请一分钟后重试", status=429)
        tx.execute("INSERT INTO account_action_tokens(token_hash,user_id,purpose,email,expires_at,created_at) VALUES(?,?,?,?,?,?)", (digest,row["id"],purpose,clean,now+1800,now))
    try:
        send_account_mail(clean, purpose, token)
    except ServiceError:
        with db.transaction() as tx:
            tx.execute("DELETE FROM account_action_tokens WHERE token_hash=?", (digest,))
        raise
    return generic


def request_email_change(db: Any, user: dict, new_email: str, current_password: str) -> dict:
    """A verified mailbox owns the recovery address. Never switch it in profile POST."""
    from .security import verify_password
    clean = str(new_email or "").strip().lower()
    if len(clean) > 120 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", clean):
        raise ServiceError("请输入有效的新邮箱地址")
    if not mail_ready():
        raise ServiceError("邮件服务尚未配置，暂时不能换绑", status=503, code="mail_unavailable")
    uid = int(user["id"])
    row = db.get_conn().execute("SELECT * FROM users WHERE id=? AND status='active'", (uid,)).fetchone()
    if not row:
        raise ServiceError("账号已失效", status=403)
    if clean == str(row["email"] or "").lower():
        raise ServiceError("新邮箱不能与当前绑定邮箱相同")
    if not verify_password(current_password, row["password_hash"],
                           password_algo=row["password_algo"], discourse_salt=row["discourse_salt"]):
        raise ServiceError("当前登录密码不正确", status=403, code="incorrect_password")
    now = int(time.time())
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with db.transaction() as tx:
        dup = tx.execute("SELECT id FROM users WHERE LOWER(email)=? AND id!=?", (clean, uid)).fetchone()
        if dup:
            raise ServiceError("该邮箱已经绑定其他账号", status=409, code="email_in_use")
        last = tx.execute(
            "SELECT created_at FROM account_action_tokens WHERE user_id=? AND purpose='email_change' ORDER BY created_at DESC LIMIT 1",
            (uid,),
        ).fetchone()
        if last and now - int(last["created_at"]) < 60:
            raise ServiceError("操作过于频繁，请一分钟后再试", status=429)
        tx.execute(
            "UPDATE account_action_tokens SET consumed_at=? WHERE user_id=? AND purpose='email_change' AND consumed_at IS NULL",
            (now, uid),
        )
        tx.execute(
            "INSERT INTO account_action_tokens(token_hash,user_id,purpose,email,expires_at,created_at) VALUES(?,?,?,?,?,?)",
            (digest, uid, "email_change", clean, now+1800, now),
        )
    try:
        send_account_mail(clean, "email_change", raw)
    except ServiceError:
        with db.transaction() as tx:
            tx.execute("DELETE FROM account_action_tokens WHERE token_hash=?", (digest,))
        raise
    return {"ok": True, "message": "验证邮件已发送到新邮箱。点击邮件链接后才会完成换绑。"}


def consume_account_token(db: Any, purpose: str, token: str, password: str = "") -> dict:
    if not token or len(token) > 200:
        raise ServiceError("链接无效或已过期")
    if purpose == "password_reset" and len(password) < 8:
        raise ServiceError("新密码至少 8 位")
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with db.transaction() as tx:
        row = tx.execute("SELECT t.*,u.email AS current_email,u.status FROM account_action_tokens t JOIN users u ON u.id=t.user_id WHERE token_hash=? AND purpose=?", (digest,purpose)).fetchone()
        if (not row or row["consumed_at"] is not None or int(row["expires_at"]) <= now
                or row["status"] != "active" or
                (purpose != "email_change" and row["email"].lower() != (row["current_email"] or "").lower())):
            raise ServiceError("链接无效或已过期，请重新申请")
        if purpose == "password_reset":
            tx.execute("UPDATE users SET password_hash=?,password_algo='pbkdf2_sha256',discourse_salt='' WHERE id=?", (hash_password(password),row["user_id"]))
            tx.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
            tx.execute("UPDATE account_action_tokens SET consumed_at=? WHERE user_id=? AND purpose=? AND consumed_at IS NULL", (now,row["user_id"],purpose))
        elif purpose == "email_change":
            existing = tx.execute("SELECT id FROM users WHERE LOWER(email)=? AND id!=?",
                                  (row["email"].lower(), row["user_id"])).fetchone()
            if existing:
                raise ServiceError("这个邮箱已被其他账号绑定，请重新换绑", status=409, code="email_in_use")
            tx.execute("UPDATE users SET email=? WHERE id=?", (row["email"], row["user_id"]))
            tx.execute("INSERT INTO verified_emails(user_id,email,verified_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,verified_at=excluded.verified_at",
                       (row["user_id"], row["email"], utc_now_iso()))
            tx.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
            tx.execute("UPDATE account_action_tokens SET consumed_at=? WHERE user_id=? AND purpose IN ('email_change','password_reset') AND consumed_at IS NULL",
                       (now, row["user_id"]))
        else:
            tx.execute("INSERT INTO verified_emails(user_id,email,verified_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,verified_at=excluded.verified_at", (row["user_id"],row["email"],utc_now_iso()))
        tx.execute("UPDATE account_action_tokens SET consumed_at=? WHERE token_hash=?", (now,digest))
    return {"ok": True, "message": (
        "密码已重置，请重新登录" if purpose == "password_reset" else
        "新邮箱已验证并完成换绑，请重新登录" if purpose == "email_change" else "邮箱验证成功"
    )}


def account_status(db: Any, user: dict) -> dict:
    row = db.get_conn().execute("SELECT email FROM verified_emails WHERE user_id=?", (user["id"],)).fetchone()
    email = user.get("email") or ""
    return {"ok":True,"email":email,"emailVerified":bool(row and row["email"].lower()==email.lower()),"mailEnabled":mail_ready()}


def list_notifications(db: Any, user: dict, before: int = 0) -> dict:
    rows = db.get_conn().execute("SELECT * FROM notifications WHERE user_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 40", (user["id"],before,before)).fetchall()
    unread = db.get_conn().execute("SELECT count(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (user["id"],)).fetchone()[0]
    return {"ok":True,"items":[dict(r) for r in rows],"unread":unread,"nextBefore":rows[-1]["id"] if len(rows)==40 else 0}


def emit_notification(tx: Any, user_id: int, kind: str, title: str, target_type: str = "", target_id: str = "") -> None:
    tx.execute("INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at) VALUES(?,?,?,?,?,?)", (user_id,kind,title[:200],target_type,target_id,utc_now_iso()))


def _owned_content(db: Any, user: dict, kind: str, item_id: str) -> dict:
    table = {"works":"works","topics":"forum_topics"}.get(kind)
    if not table:
        raise ServiceError("内容类型不存在",status=404)
    row = db.get_conn().execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
    if not row or row["status"] == "deleted":
        raise ServiceError("内容不存在",status=404)
    if row["author_username"] != user["username"]:
        raise ServiceError("只能编辑自己发布的内容",status=403)
    result = dict(row)
    if kind == "works":
        from .services import get_work_client_prompt
        safe_p, was_masked = get_work_client_prompt(result, is_admin_route=False)
        result["prompt"] = safe_p
        if was_masked:
            result["promptMasked"] = True
            result["subject"] = ""
    elif kind == "topics":
        from .runtime_policy import sanitize_html
        result["summary"] = sanitize_html(result["summary"])
        result["locked_body"] = sanitize_html(result["locked_body"])
        from .services import get_topic_client_recipe_json
        safe_recipe, was_masked = get_topic_client_recipe_json(result, is_admin_route=False, conn=db.get_conn())
        result["recipe_json"] = json.dumps(safe_recipe, ensure_ascii=False) if safe_recipe is not None else ""
        if was_masked:
            result["promptMasked"] = True
    return result


def edit_owned_content(db: Any, user: dict, kind: str, item_id: str, body: dict) -> dict:
    row = _owned_content(db,user,kind,item_id)
    if kind == 'works':
        sub=db.get_conn().execute("SELECT id,current_revision FROM curation_submissions WHERE kind='work' AND target_id=?",(item_id,)).fetchone()
        if sub:
            from .curation import revise, _current_payload
            payload=_current_payload(db.get_conn(),sub['id'],sub['current_revision'])
            req_prompt = body.get("prompt")
            if req_prompt and req_prompt != "[包含资源专属指令，已隐藏]":
                payload["prompt"] = req_prompt
            req_subject = body.get("subject")
            if req_subject and req_subject != "[包含资源专属指令，已隐藏]":
                payload["subject"] = req_subject
            if "title" in body:
                payload["title"] = body["title"]
            if "notes" in body:
                payload["notes"] = body["notes"]
            if "price" in body:
                payload["price"] = body["price"]
            return revise(db,user,sub['id'],{'payload':payload})
    title = str(body.get("title",row["title"])).strip()
    if not 4 <= len(title) <= 140:
        raise ServiceError("标题需为 4～140 个字")
    now = utc_now_iso()
    with db.transaction() as tx:
        if kind == "works":
            if "price" in body:
                raw_price = body.get("price")
                if raw_price not in (None, ""):
                    try:
                        if isinstance(raw_price, float) and (raw_price != raw_price or raw_price in (float("inf"), float("-inf"))):
                            raise ValueError("non-finite price")
                        parsed_price = int(raw_price)
                    except (TypeError, ValueError, OverflowError):
                        raise ServiceError("作品定价必须是整数", status=400, code="invalid_price")
                    if parsed_price != 0:
                        raise ServiceError("作品不支持收费定价", status=400, code="work_price_not_allowed")
            cur_work = tx.execute("SELECT prompt, prompt_has_secret, subject FROM works WHERE id=?", (item_id,)).fetchone()
            cur_prompt = str(cur_work["prompt"] or "") if cur_work else ""
            cur_has_sec = cur_work["prompt_has_secret"] if cur_work else 0
            cur_subject = str(cur_work["subject"] or "") if (cur_work and "subject" in cur_work.keys()) else ""

            # If author omits prompt, or sends empty string/placeholder, keep stored prompt and flag
            req_prompt = body.get("prompt")
            if req_prompt is None or req_prompt == "" or req_prompt == "[包含资源专属指令，已隐藏]":
                prompt = cur_prompt
                prompt_provided = False
            else:
                prompt = str(req_prompt)
                if not prompt.strip() or len(prompt) > 20000:
                    raise ServiceError("请填写有效的实际提示词（最多 20000 字）")
                prompt_provided = True

            req_subject = body.get("subject")
            if req_subject is None or req_subject == "[包含资源专属指令，已隐藏]":
                subject = cur_subject
                subject_provided = False
            else:
                subject = str(req_subject)
                if len(subject) > 2000:
                    raise ServiceError("主题内容过长（最多2000字）")
                subject_provided = True

            if not prompt_provided and not subject_provided:
                prompt_has_sec = cur_has_sec
            else:
                from .services import check_text_has_secret
                try:
                    has_sec = check_text_has_secret(prompt, tx) or check_text_has_secret(subject, tx)
                    prompt_has_sec = 1 if has_sec else 0
                except Exception:
                    prompt_has_sec = None
            notes = str(body.get("notes", row["notes"]))[:20000]
            tx.execute("UPDATE works SET title=?,prompt=?,prompt_has_secret=?,notes=?,subject=?,updated_at=? WHERE id=? AND author_username=?", (title,prompt,prompt_has_sec,notes,subject,now,item_id,user["username"]))
        else:
            from .runtime_policy import sanitize_html
            summary = sanitize_html(str(body.get("body",row["summary"])))
            locked = sanitize_html(str(body.get("lockedBody",row["locked_body"])))
            if not summary.strip() or len(summary) > 60000 or len(locked) > 60000:
                raise ServiceError("正文不能为空且不得超过 60000 字")
            tx.execute("UPDATE forum_topics SET title=?,summary=?,locked_body=?,updated_at=? WHERE id=? AND author_username=?", (title,summary,locked,now,item_id,user["username"]))
        record_audit_log(tx,user,"author_edit", "work" if kind=="works" else "topic",item_id,details={"title":title})
    if kind == "works":
        try:
            from .home_scenarios import invalidate_scenarios_cache
            invalidate_scenarios_cache()
        except Exception:
            pass
    return {"ok":True,"id":item_id}


def handle_feature_get(handler: Any, req_path: str, qs: dict) -> bool:
    if req_path == "/api/guides":
        editorial=json.loads((CONTENT_DIR/"editorial.json").read_text(encoding="utf-8"))
        items=[]
        for item in editorial.get("guides",[]):
            topic_id=item.get("topic_id")
            if not isinstance(topic_id,int) or topic_id<=0:continue
            items.append({"title":str(item.get("title") or "教程"),"summary":str(item.get("summary") or ""),"url":f"https://handraw-style.com/t/topic/{topic_id}"})
        handler._send_json({"ok":True,"items":items});return True
    if req_path == "/api/account/status":
        user = handler._current_user(required=True)
        handler._send_json(account_status(handler.db,user));return True
    if req_path == "/api/account/sessions":
        user = handler._current_user(required=True)
        from .security import hash_session_token
        current = hash_session_token(str(user.get("_session_token") or "")) if user.get("_session_token") else ""
        rows = handler.db.get_conn().execute(
            "SELECT rowid AS session_id, token, user_agent, created_at, expires_at FROM sessions WHERE user_id=? AND expires_at>? ORDER BY created_at DESC LIMIT 30",
            (user["id"], int(time.time())),
        ).fetchall()
        handler._send_json({"ok": True, "items": [
            {"id": r["session_id"], "device": (r["user_agent"] or "未知设备")[:160],
             "createdAt": r["created_at"], "current": bool(current and r["token"] == current)}
            for r in rows
        ]});return True
    if req_path == "/api/notifications":
        user = handler._current_user(required=True)
        try:before=max(0,int((qs.get("before") or ["0"])[0]))
        except (ValueError,TypeError):raise ServiceError("分页参数无效")
        handler._send_json(list_notifications(handler.db,user,before));return True
    match = re.fullmatch(r"/api/content/(works|topics)/([^/]+)/edit",req_path)
    if match:
        user = handler._current_user(required=True)
        handler._send_json({"ok":True,"item":_owned_content(handler.db,user,*match.groups())});return True
    return False


def handle_feature_post(handler: Any, req_path: str, body: dict) -> bool:
    if req_path == "/api/account/sessions/revoke-others":
        user = handler._current_user(required=True)
        from .security import verify_password, hash_session_token
        current_row = handler.db.get_conn().execute(
            "SELECT password_hash,password_algo,discourse_salt FROM users WHERE id=? AND status='active'",
            (user["id"],),
        ).fetchone()
        if not current_row or not verify_password(str(body.get("currentPassword") or ""),
            current_row["password_hash"], password_algo=current_row["password_algo"],
            discourse_salt=current_row["discourse_salt"]):
            raise ServiceError("当前登录密码不正确", status=403, code="incorrect_password")
        current = hash_session_token(str(user.get("_session_token") or "")) if user.get("_session_token") else ""
        with handler.db.transaction() as tx:
            result = tx.execute(
                "DELETE FROM sessions WHERE user_id=? AND token!=?",
                (user["id"], current),
            )
        handler._send_json({"ok": True, "revoked": result.rowcount});return True
    if req_path == "/api/account/avatar":
        user = handler._current_user(required=True)
        from .avatar_identity import save_avatar
        handler._send_json(save_avatar(handler.db, user, str(body.get("dataUrl") or "")))
        return True
    if req_path == "/api/account/avatar/reset":
        user = handler._current_user(required=True)
        from .avatar_identity import reset_avatar
        handler._send_json(reset_avatar(handler.db, user))
        return True
    if req_path == "/api/auth/change-email":
        user = handler._current_user(required=True)
        handler._send_json(request_email_change(handler.db,user,
            str(body.get("email") or ""), str(body.get("currentPassword") or "")))
        return True
    if req_path == "/api/auth/confirm-email-change":
        handler._send_json(consume_account_token(handler.db,"email_change",
            str(body.get("token") or "")))
        return True
    if req_path == "/api/auth/forgot-password":
        handler._send_json(request_account_mail(handler.db,"password_reset",str(body.get("email") or "")));return True
    if req_path == "/api/auth/reset-password":
        handler._send_json(consume_account_token(handler.db,"password_reset",str(body.get("token") or ""),str(body.get("password") or "")));return True
    if req_path == "/api/auth/send-verification":
        user = handler._current_user(required=True)
        handler._send_json(request_account_mail(handler.db,"verify_email",str(user.get("email") or ""),user));return True
    if req_path == "/api/auth/verify-email":
        handler._send_json(consume_account_token(handler.db,"verify_email",str(body.get("token") or "")));return True
    if req_path == "/api/notifications/read":
        user = handler._current_user(required=True)
        with handler.db.transaction() as tx:
            if body.get("all"):
                tx.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (utc_now_iso(),user["id"]))
            else:
                tx.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND id=?", (utc_now_iso(),user["id"],int(body.get("id") or 0)))
        handler._send_json({"ok":True});return True
    match = re.fullmatch(r"/api/content/(works|topics)/([^/]+)/edit",req_path)
    if match:
        user=handler._current_user(required=True)
        handler._send_json(edit_owned_content(handler.db,user,*match.groups(),body));return True
    if req_path == "/api/studio/history/delete":
        from .services import delete_user_studio_history
        user=handler._current_user(required=True)
        if body.get("all"):
            ids = handler.db.get_conn().execute("SELECT id FROM studio_generations WHERE user_id=? AND status IN ('success','failed','refunded','cancelled')", (user["id"],)).fetchall()
            for row in ids:
                delete_user_studio_history(handler.db,user,row["id"])
            handler._send_json({"ok":True,"deleted":len(ids)})
        else:
            handler._send_json(delete_user_studio_history(handler.db,user,str(body.get("id") or "")))
        return True
    return False
