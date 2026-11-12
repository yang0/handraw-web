"""Create and query discussion topics shared by works, resources, and the forum."""
from __future__ import annotations

from functools import lru_cache
import json
import time
import uuid
import re
from datetime import datetime, timezone

from .config import CONTENT_DIR
from . import services as S
from .postgres_db import PgConnection
from .runtime_policy import sanitize_html, sanitize_media_url, sanitize_plain_text

@lru_cache(maxsize=1)
def static_catalog():
    data=json.loads((CONTENT_DIR/'catalog.json').read_text(encoding='utf-8'))
    return {r['id']:r for r in data.get('resources',[]) if r.get('kind') in ('style','layout')}


def find_topic_source(db, topic_id):
    row=db.get_conn().execute('SELECT * FROM curation_resource_topics WHERE topic_id=? ORDER BY origin=\'submission\' DESC LIMIT 1',(topic_id,)).fetchone()
    return dict(row) if row else None


def resolve_resource(conn,kind,target,viewer=None,include_pending=False):
    if kind=='work':
        row=conn.execute("SELECT * FROM works WHERE id=? AND status='published'",(target,)).fetchone()
        return dict(row) if row and (S.is_demo_mode() or target not in S.seed_ids('works')) else None
    if kind not in ('style','layout'):
        return None
    from . import resource_registry
    res = resource_registry.resolve(conn, target, viewer=viewer, purpose="view")
    if not res:
        return None
    if res.get("kind") != kind:
        return None
    if not include_pending and res.get("status") != "published":
        return None
    if res.get("status") == "withdrawn":
        return None

    # 1. catalog_assets: Return full DB row dictionary for backward compatibility with _asset_resource
    if res.get("_raw_row"):
        if res.get("status") == "published" and (S.is_demo_mode() or res["code"] not in S.seed_ids('assets')):
            return dict(res["_raw_row"])
        return None

    # 2. static catalog.json: Return item dict (keys: id, name, ..., NO "code")
    if res.get("source") == "official":
        item = static_catalog().get(res["code"])
        if item and item.get("kind") == kind:
            return item

    # 3. curation_submissions (pending): Return pending dict (keys: id, name, ..., NO "code", pending: True)
    # Notice: It MUST NOT contain "code", so forum_resources and post_routes take the _static_resource branch.
    is_pending = res.get("status") in ("pending", "changes_requested") or res.get("source") == "pending"
    return {
        "id": res["code"],
        "name": res["name"],
        "description": res.get("description") or "",
        "definition": res.get("definition") or "",
        "image": res.get("image") or "",
        "unlockCost": 0,
        "sourceType": "community",
        "author": res.get("author") or "",
        "authorName": res.get("authorName") or res.get("author") or "",
        "status": res.get("status") or "pending",
        "pending": is_pending,
        "definitionHidden": not bool(res.get("definition")),
    }


def _pending_submission_resource(conn, kind, target_norm, viewer=None):
    """A resource that exists only as a submission still owns its topic.

    Without this the author is sent to their brand new topic right after
    publishing and the detail endpoint answers 404, so publishing looks broken
    until a moderator approves the entry.
    """
    return resolve_resource(conn, kind, target_norm, viewer=viewer, include_pending=True)



def _sync_work_topic_media(tx, topic_id, work_id, work):
    """Keep a discussion's image gallery consistent with its canonical work.

    A work gains images as the parallel generation slots complete. Creating a
    topic on the first image must not permanently freeze the topic at one image.
    """
    images = json.loads(work.get("images_json") or "[]")
    urls = [sanitize_media_url(i.get("url", "") if isinstance(i, dict) else str(i or ""))
            for i in images]
    urls = [url for url in urls if url][:12]
    tx.execute(
        "UPDATE forum_topics SET images_json=?, updated_at=? WHERE id=? AND work_id=?",
        (json.dumps(urls, ensure_ascii=False), S.utc_now_iso(), topic_id, work_id),
    )


def ensure_topic(tx, kind, target, resource, initial_origin: str = 'submission', listed_at_ms: int | None = None):
    if kind in ('style', 'layout', 'asset'):
        target = str(target or '').strip().upper().lstrip('#')
    else:
        target = str(target or '').strip()

    now = S.utc_now_iso()

    # 1. Check existing curation mapping
    if kind in ('style', 'layout', 'asset'):
        row = tx.execute('SELECT topic_id, origin FROM curation_resource_topics WHERE kind=? AND UPPER(target_id)=?', (kind, target)).fetchone()
    else:
        row = tx.execute('SELECT topic_id, origin FROM curation_resource_topics WHERE kind=? AND target_id=?', (kind, target)).fetchone()
    if row:
        if kind == 'work':
            _sync_work_topic_media(tx, str(row['topic_id']), target, resource)
        return str(row['topic_id'])

    # 2. For works, check if a topic already exists for this work_id (in any status)
    if kind == 'work':
        existing = tx.execute('SELECT id, status, status_source, status_actor_role FROM forum_topics WHERE work_id=?', (target,)).fetchone()
        if existing:
            tid = str(existing['id'])
            tx.execute(
                'INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING',
                (kind, target, tid, initial_origin, now),
            )
            _sync_work_topic_media(tx, tid, target, resource)
            return tid

    tid = 'topic_' + uuid.uuid4().hex
    label = {'style': '画风', 'layout': '图型', 'work': '作品'}[kind]
    name = resource.get('name') or resource.get('title') or target
    if not re.search(r'[\u3400-\u9fff]', name):
        chinese = re.split(r'[、，,。；;]', str(resource.get('description') or ''))[0].strip()
        name = chinese[:18] if re.search(r'[\u3400-\u9fff]', chinese) else label
    images = json.loads(resource.get('images_json') or '[]') if kind == 'work' else [resource.get('image_url') or resource.get('image')]
    images = [sanitize_media_url(i.get('url', '') if isinstance(i, dict) else str(i or '')) for i in images]
    images = [i for i in images if i][:12]

    category = 'showcase' if kind == 'work' else 'assets'
    category_label = '🎨 作品讨论' if kind == 'work' else '画风与图型专区'
    is_community_asset = (kind != 'work') and (resource.get('source_type') == 'community')

    t_status = 'published'
    t_source = ''
    t_reason = ''
    t_actor = ''

    if kind == 'work':
        author_username = str(resource.get('author_username') or '')
        author_name = str(resource.get('author_name') or '作品作者')
        title = resource.get('title') or name
        summary = str(resource.get('notes') or resource.get('summary') or '')
        w_st = str(resource.get('status') or 'published')
        if w_st != 'published':
            t_status = w_st
            t_source = 'work'
            t_reason = str(resource.get('status_reason') or '')
            t_actor = str(resource.get('status_actor_role') or '')
    elif is_community_asset:
        author_username = str(resource.get('author_username') or '')
        author_name = str(resource.get('author_name') or author_username or '社区创作者')
        title = f'{name} · {label}讨论'
        summary = f'围绕这项{label}交流使用心得。'
    else:
        author_username = ''
        author_name = '资源讨论'
        title = f'{name} · {label}讨论'
        summary = f'围绕这项{label}交流使用心得。'

    pub_ms = int(time.time() * 1000)
    topic_listed = listed_at_ms if listed_at_ms is not None else (pub_ms if kind != 'work' else None)

    # 3. Insert topic and mapping wrapped in a SAVEPOINT to cleanly resolve concurrent collisions
    sp_name = f"sp_ensure_{uuid.uuid4().hex[:8]}"
    tx.execute(f"SAVEPOINT {sp_name}")
    try:
        inserted = tx.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, title, author_username, author_name, summary,
                images_json, styles_json, layout_code, work_id,
                status, status_source, status_reason, status_actor_role,
                published_at_ms, created_label, created_at, updated_at, listed_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '刚刚', ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                tid,
                category,
                category_label,
                title,
                author_username,
                author_name,
                summary,
                json.dumps(images, ensure_ascii=False),
                json.dumps([target] if kind == 'style' else []),
                target if kind == 'layout' else '',
                target if kind == 'work' else '',
                t_status,
                t_source,
                t_reason,
                t_actor,
                pub_ms,
                now,
                now,
                topic_listed,
            ),
        )
        if inserted.rowcount:
            mapped = tx.execute(
                'INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING',
                (kind, target, tid, initial_origin, now),
            )
            if mapped.rowcount:
                tx.execute(f"RELEASE SAVEPOINT {sp_name}")
                return tid
    except BaseException:
        tx.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
        tx.execute(f"RELEASE SAVEPOINT {sp_name}")
        raise

    tx.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
    tx.execute(f"RELEASE SAVEPOINT {sp_name}")

    # A concurrent writer won the insert. Resolve its mapping after releasing
    # our savepoint so the losing attempt leaves no orphan topic.
    if kind == 'work':
        existing = tx.execute('SELECT id FROM forum_topics WHERE work_id=?', (target,)).fetchone()
        if existing:
            tid = str(existing['id'])
            tx.execute(
                'INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING',
                (kind, target, tid, initial_origin, now),
            )
            return tid

    if kind in ('style', 'layout', 'asset'):
        row = tx.execute('SELECT topic_id FROM curation_resource_topics WHERE kind=? AND UPPER(target_id)=?', (kind, target)).fetchone()
    else:
        row = tx.execute('SELECT topic_id FROM curation_resource_topics WHERE kind=? AND target_id=?', (kind, target)).fetchone()
    if row:
        return str(row['topic_id'])
    raise RuntimeError("Could not resolve discussion topic after a conflicting insert")


def record_atomic_reply_and_listing(
    tx: PgConnection,
    topic_id: str,
    user: dict[str, Any],
    clean_text: str,
    mounted_style: str = "",
    mounted_layout: str = "",
) -> tuple[str, int]:
    """Execute reply creation and first-time listing atomically within an existing transaction."""
    topic = tx.execute("SELECT id, status, work_id, listed_at_ms FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic or topic["status"] != "published":
        raise S.ServiceError("讨论已暂停", status=409)

    # If linked to a work, verify the work status is also published
    linked_wid = str(topic["work_id"] or "").strip()
    if not linked_wid:
        m = tx.execute("SELECT target_id FROM curation_resource_topics WHERE kind = 'work' AND topic_id = ?", (topic_id,)).fetchone()
        if m:
            linked_wid = str(m["target_id"]).strip()

    if linked_wid:
        w_cur = tx.execute("SELECT status FROM works WHERE id = ?", (linked_wid,)).fetchone()
        if w_cur and str(w_cur["status"]) != "published":
            raise S.ServiceError("讨论已暂停", status=409)

    now_iso = S.utc_now_iso()
    now_ms = int(time.time() * 1000)
    rid = f"rep_{now_ms}_{uuid.uuid4().hex[:4]}"

    tx.execute(
        """
        INSERT INTO forum_replies (
            id, topic_id, author_username, author_name, text, mounted_style, mounted_layout,
            likes, accepted, status, time_label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'published', '刚刚', ?)
        """,
        (
            rid,
            topic_id,
            user["username"],
            user["display_name"],
            clean_text,
            mounted_style,
            mounted_layout,
            now_iso,
        ),
    )

    # First-time listing: only sets listed_at_ms when currently NULL, never refreshes if already set
    tx.execute(
        "UPDATE forum_topics SET listed_at_ms = ?, updated_at = ? WHERE id = ? AND listed_at_ms IS NULL",
        (now_ms, now_iso, topic_id),
    )

    uid = int(user["id"])
    bal_row = tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
    if bal_row:
        cur_bal = int(bal_row["balance"])
    else:
        tx.execute(
            "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 0, '', 0, '', 0, ?)",
            (uid, now_iso),
        )
        cur_bal = 0

    return rid, cur_bal


def comment(db,user,kind,target_id,text,request_id=None):
    target=str(target_id).strip().upper().lstrip('#') if kind!='work' else str(target_id).strip()
    clean=sanitize_plain_text(str(text or '').strip(), max_chars=3000)
    if not clean:
        raise S.ServiceError('请输入评论内容')
    with db.transaction() as tx:
        # Deduplication receipt and forum reply share the same transaction.
        receipt_hash = None
        if request_id:
            if kind != 'work':
                raise S.ServiceError('幂等评论仅支持作品', status=400, code='invalid_request')
            import hashlib
            receipt_hash = hashlib.sha256((target + '\n' + clean).encode('utf-8')).hexdigest()
            old = tx.execute(
                'SELECT work_id,body_hash,response_json FROM skill_comment_receipts '
                'WHERE user_id=? AND request_id=?',
                (int(user['id']), request_id)
            ).fetchone()
            if old:
                if old['work_id'] != target or old['body_hash'] != receipt_hash:
                    raise S.ServiceError('重复请求内容不一致', status=409, code='idempotency_conflict')
                return json.loads(old['response_json'])
        resource=resolve_resource(tx,kind,target)
        if not resource:
            raise S.ServiceError('资源不存在或尚未收录',status=404)

        if kind == 'work':
            # Check if topic already exists for this work
            mapping = tx.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
                (target,),
            ).fetchone()
            if not mapping:
                existing_topic = tx.execute("SELECT id FROM forum_topics WHERE work_id = ?", (target,)).fetchone()
                if existing_topic:
                    tid = str(existing_topic["id"])
                    tx.execute(
                        "INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', ?, ?, 'submission', ?) ON CONFLICT DO NOTHING",
                        (target, tid, S.utc_now_iso()),
                    )
                else:
                    tid = None
            else:
                tid = str(mapping["topic_id"])

            if not tid:
                # Work has NO topic yet (fallback for historical missing topics):
                # Ensure topic is created atomically (both author and others can comment)
                tid = ensure_topic(tx, kind, target, resource)
        else:
            tid = ensure_topic(tx, kind, target, resource)

        rid, cur_bal = record_atomic_reply_and_listing(
            tx,
            tid,
            user,
            clean,
        )
        result = {
            "ok": True, "topicId": tid, "replyId": rid, "rewarded": 0,
            "credits": cur_bal, "assetCode": target if kind != 'work' else None,
            "assetKind": kind,
            "comment": {"id": rid, "user": user["username"], "name": user["display_name"],
                        "text": clean, "time": "刚刚"},
        }
        if request_id:
            tx.execute(
                'INSERT INTO skill_comment_receipts'
                '(user_id,request_id,work_id,body_hash,response_json,created_at)'
                ' VALUES(?,?,?,?,?,?)',
                (int(user['id']), request_id, target, receipt_hash,
                 json.dumps(result, ensure_ascii=False), S.utc_now_iso())
            )
    return result


def _activity(conn,replies,fallback):
    # Only timestamps for already-filtered public comment IDs participate.
    ids=[r['id'] for r in replies if r.get('id')]
    latest=0
    if ids:
        ph=','.join('?' for _ in ids)
        for table in ('asset_comments','work_comments','forum_replies'):
            row=conn.execute(f"SELECT MAX(created_at) FROM {table} WHERE id IN ({ph}) AND status='published'",ids).fetchone()
            if row and row[0]:
                latest=max(latest,int(datetime.fromisoformat(row[0].replace('Z','+00:00')).replace(tzinfo=timezone.utc).timestamp()*1000))
    return latest or fallback


OFFICIAL_TOPIC_MIN_REPLIES = 1


def official_topic_ids_sql() -> str:
    """Return SQL subquery selecting topic_ids of official style/layout discussion topics."""
    return (
        "SELECT m.topic_id FROM curation_resource_topics m "
        "WHERE m.kind IN ('style', 'layout') "
        "AND NOT EXISTS (SELECT 1 FROM curation_submissions s WHERE s.topic_id = m.topic_id) "
        "AND NOT EXISTS (SELECT 1 FROM catalog_assets a "
        "WHERE UPPER(a.code) = UPPER(m.target_id) AND a.kind = m.kind "
        "AND a.source_type = 'community')"
    )


def topic_visibility_sql(reply_filter: str = "1=1", admin: bool = False) -> str:
    """Return SQL condition for topic visibility.

    Official style/layout topics are hidden from the topic list unless they have >= OFFICIAL_TOPIC_MIN_REPLIES.
    When admin=False (public boot & stats), replies must have status='published' and satisfy reply_filter.
    When admin=True (admin views & stats), replies of any status satisfying reply_filter count.
    Work-associated topics must have listed_at_ms IS NOT NULL to appear in the topic list.
    """
    official_sql = official_topic_ids_sql()
    rf = reply_filter if reply_filter and reply_filter.strip() else "1=1"
    if admin:
        reply_cond = (
            f"(SELECT COUNT(*) FROM forum_replies r "
            f"WHERE r.topic_id = forum_topics.id AND {rf}) >= {OFFICIAL_TOPIC_MIN_REPLIES}"
        )
    else:
        reply_cond = (
            f"(SELECT COUNT(*) FROM forum_replies r "
            f"WHERE r.topic_id = forum_topics.id AND r.status = 'published' AND {rf}) >= {OFFICIAL_TOPIC_MIN_REPLIES}"
        )
    if admin:
        work_cond = "1=1"
    else:
        work_cond = (
            "("
            "  ("
            "    (forum_topics.work_id IS NULL OR forum_topics.work_id = '') "
            "    AND NOT EXISTS (SELECT 1 FROM curation_resource_topics crt_w WHERE crt_w.kind = 'work' AND crt_w.topic_id = forum_topics.id)"
            "  ) "
            "  OR forum_topics.listed_at_ms IS NOT NULL"
            ")"
        )
    return f"((id NOT IN ({official_sql}) OR {reply_cond}) AND {work_cond})"


def apply_boot(db, payload, current_user):
    conn = db.get_conn()
    for w in payload.get('works', []):
        w['comments'] = []
    payload['assetComments'] = {}
    works = {w['id']: w for w in payload.get('works', [])}
    assets = payload['assetComments']
    topics = {t['id']: t for t in payload.get('topics', [])}
    hidden = set()
    payload['discussions'] = {}
    for row in conn.execute('SELECT * FROM curation_resource_topics').fetchall():
        kind, target, tid, origin = row['kind'], row['target_id'], row['topic_id'], row['origin']
        norm_target = target.upper().lstrip('#') if kind in ('style', 'layout') else target
        topic = topics.get(tid)
        if not topic:
            if kind == 'work':
                st_row = conn.execute(
                    """
                    SELECT ft.status AS topic_status, w.status AS work_status
                    FROM forum_topics ft
                    JOIN works w ON w.id = ?
                    WHERE ft.id = ?
                    """,
                    (target, tid),
                ).fetchone()
                if st_row and st_row["topic_status"] == "published" and st_row["work_status"] == "published":
                    reply_cnt_row = conn.execute(
                        "SELECT COUNT(*) AS c FROM forum_replies WHERE topic_id = ? AND status = 'published'",
                        (tid,),
                    ).fetchone()
                    reply_cnt = int(reply_cnt_row["c"]) if reply_cnt_row else 0
                    payload['discussions'][norm_target] = {'topicId': tid, 'count': reply_cnt, 'origin': origin}
            continue
        replies = topic.get('replies', [])
        # A work is not a catalogue resource: resolve_resource() only knows
        # styles, layouts and assets, so asking it about a work always answers
        # None and the topic was then dropped from the list. Works carry their
        # own row and their own topic, so they need no such check.
        if kind == 'work':
            if target in works:
                works[target]['comments'] = replies
            raw = works.get(target) or {'id': target}
        else:
            raw = resolve_resource(conn, kind, norm_target)
            assets[norm_target] = replies
        if not raw:
            is_pending_submission = (
                kind in ('style', 'layout')
                and conn.execute('SELECT 1 FROM curation_submissions WHERE topic_id = ?', (tid,)).fetchone() is not None
                and conn.execute('SELECT 1 FROM catalog_assets WHERE (code = ? OR UPPER(code) = ?) AND kind = ?', (norm_target, norm_target, kind)).fetchone() is None
            )
            if not is_pending_submission:
                hidden.add(tid)
                continue
        topic['resourceDiscussion'] = {'kind': kind, 'targetId': norm_target, 'origin': origin, 'commentCount': len(replies)}
        topic['activityAtMs'] = _activity(conn, replies, topic['publishedAtMs'])
        payload['discussions'][norm_target] = {'topicId': tid, 'count': len(replies), 'origin': origin}
    payload['topics'] = [t for tid, t in topics.items() if tid not in hidden]
    return payload
