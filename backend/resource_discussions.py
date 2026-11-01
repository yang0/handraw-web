"""One comment store per discussion, adapted from the reviewed DeepSeek proposal.

Official resources keep asset_comments; collected submissions keep forum_replies.
Boot projects these same rows into both views without copying stored comments.
"""
from __future__ import annotations

from functools import lru_cache
import json
import time
import uuid
import re
from datetime import datetime, timezone

from .config import CONTENT_DIR
from . import services as S
from .runtime_policy import sanitize_html, sanitize_media_url


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
        return dict(row) if row and str(row['prompt'] or '').strip() and (S.is_demo_mode() or target not in S.seed_ids('works')) else None
    if kind not in ('style','layout'):
        return None
    target_norm = str(target or '').strip().upper().lstrip('#')
    row=conn.execute('SELECT * FROM catalog_assets WHERE (code=? OR UPPER(code)=?) AND kind=?',(target_norm, target_norm, kind)).fetchone()
    if row:
        return dict(row) if row['status']=='published' and (S.is_demo_mode() or target_norm not in S.seed_ids('assets')) else None
    item=static_catalog().get(target_norm)
    if item and item['kind']==kind:
        return item
    if include_pending:
        return _pending_submission_resource(conn, kind, target_norm, viewer)
    return None


def _pending_submission_resource(conn, kind, target_norm, viewer=None):
    """A resource that exists only as a submission still owns its topic.

    Without this the author is sent to their brand new topic right after
    publishing and the detail endpoint answers 404, so publishing looks broken
    until a moderator approves the entry.
    """
    row = conn.execute(
        "SELECT s.owner_username, s.status, v.payload_json "
        "FROM curation_submissions s "
        "JOIN curation_versions v ON v.submission_id = s.id AND v.revision = s.current_revision "
        "WHERE UPPER(s.target_id) = ? AND s.kind = ? AND s.status <> 'withdrawn' "
        "ORDER BY s.updated_at DESC LIMIT 1",
        (target_norm, kind),
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    owner = str(row["owner_username"] or "")
    viewer_name = ""
    if isinstance(viewer, dict):
        viewer_name = str(viewer.get("username") or "")
    can_read_definition = bool(viewer_name) and viewer_name == owner
    cover = payload.get("cover") or payload.get("image") or ""
    images = payload.get("images") or []
    if not cover and images:
        first = images[0]
        cover = first.get("url", "") if isinstance(first, dict) else str(first or "")
    return {
        "id": target_norm,
        "name": payload.get("name") or target_norm,
        "description": payload.get("description") or "",
        "definition": (payload.get("definition") or "") if can_read_definition else "",
        "image": sanitize_media_url(cover),
        "unlockCost": 0,
        "sourceType": "community",
        "author": owner,
        "authorName": owner,
        "status": "pending",
        "pending": True,
        "definitionHidden": not can_read_definition,
    }


def ensure_topic(tx,kind,target,resource,initial_origin: str = 'submission'):
    if kind in ('style', 'layout', 'asset'):
        target = str(target or '').strip().upper().lstrip('#')
    else:
        target = str(target or '').strip()

    if kind in ('style', 'layout', 'asset'):
        row = tx.execute('SELECT topic_id, origin FROM curation_resource_topics WHERE kind=? AND UPPER(target_id)=?', (kind, target)).fetchone()
    else:
        row = tx.execute('SELECT topic_id, origin FROM curation_resource_topics WHERE kind=? AND target_id=?', (kind, target)).fetchone()
    if row:
        return row['topic_id']

    now = S.utc_now_iso()

    # Reuse existing topic if already created for this work (in any status)
    if kind == 'work':
        existing = tx.execute('SELECT id, status, status_source, status_actor_role FROM forum_topics WHERE work_id=?', (target,)).fetchone()
        if existing:
            tid = str(existing['id'])
            tx.execute(
                'INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES (?, ?, ?, ?, ?)',
                (kind, target, tid, initial_origin, now),
            )
            return tid

    tid = 'topic_' + uuid.uuid4().hex
    label = {'style': '画风', 'layout': '图型', 'work': '作品'}[kind]
    name = resource.get('name') or resource.get('title') or target
    if not re.search(r'[\u3400-\u9fff]', name):
        chinese = re.split(r'[、，,。；;]', str(resource.get('description') or ''))[0].strip()
        name = chinese[:18] if re.search(r'[\u3400-\u9fff]', chinese) else label
    images = json.loads(resource.get('images_json') or '[]') if kind == 'work' else [resource.get('image_url') or resource.get('image')]
    images = [sanitize_media_url(i.get('url', '') if isinstance(i, dict) else str(i or '')) for i in images]
    images = [i for i in images if i][:9]

    category = 'showcase' if kind == 'work' else 'assets'
    category_label = '🎨 晒作品' if kind == 'work' else '画风与图型专区'
    is_community_asset = (kind != 'work') and (resource.get('source_type') == 'community')

    t_status = 'published'
    t_source = ''
    t_reason = ''
    t_actor = ''

    if kind == 'work':
        author_username = str(resource.get('author_username') or '')
        author_name = str(resource.get('author_name') or '作品作者')
        title = resource.get('title') or name
        summary = ''
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

    tx.execute(
        """
        INSERT INTO forum_topics (
            id, category, category_label, title, author_username, author_name, summary,
            images_json, styles_json, layout_code, work_id,
            status, status_source, status_reason, status_actor_role,
            published_at_ms, created_label, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '刚刚', ?, ?)
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
            int(time.time() * 1000),
            now,
            now,
        ),
    )
    tx.execute(
        'INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES (?, ?, ?, ?, ?)',
        (kind, target, tid, initial_origin, now),
    )
    return tid


def comment(db,user,kind,target_id,text):
    target=str(target_id).strip().upper().lstrip('#') if kind!='work' else str(target_id).strip()
    clean=sanitize_html(str(text or '').strip())[:800]
    if not clean:
        raise S.ServiceError('请输入评论内容')
    with db.transaction() as tx:
        resource=resolve_resource(tx,kind,target)
        if not resource:
            raise S.ServiceError('资源不存在或尚未收录',status=404)
        tid=ensure_topic(tx,kind,target,resource)
        topic=tx.execute('SELECT status FROM forum_topics WHERE id=?',(tid,)).fetchone()
        if not topic or topic['status']!='published':
            raise S.ServiceError('讨论已暂停',status=409)
    result=S.publish_forum_reply_post(db,user,tid,clean,direct=True)
    result['topicId']=tid
    result['replyId']=result.get('replyId')
    result['assetCode']=target if kind!='work' else None
    result['assetKind']=kind
    result['comment']={'id':result['replyId'],'user':user['username'],'name':user['display_name'],'text':clean,'time':'刚刚'}
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
    return f"(id NOT IN ({official_sql}) OR {reply_cond})"


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
            continue
        replies = topic.get('replies', [])
        raw = resolve_resource(conn, kind, norm_target)
        if kind == 'work':
            if target in works:
                works[target]['comments'] = replies
        else:
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
