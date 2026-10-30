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


def resolve_resource(conn,kind,target):
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
    return item if item and item['kind']==kind else None


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
    is_community_asset = (kind != 'work') and (
        resource.get('source_type') == 'community' or bool(resource.get('author_username'))
    )

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


def is_resource_placeholder(conn: Any, topic_id: str, kind: str) -> bool:
    """Return True if topic is a resource placeholder (style/layout not submitted via curation_submissions)."""
    if kind not in ('style', 'layout'):
        return False
    is_submission = conn.execute("SELECT 1 FROM curation_submissions WHERE topic_id = ?", (topic_id,)).fetchone()
    return is_submission is None


def placeholder_topic_sql_filter(kind: str = "public") -> str:
    """SQL filter ensuring resource placeholder topics appear only when they have replies.

    kind="public": requires status='published' replies (for boot, creator stats).
    kind="admin": requires any reply in forum_replies (for admin dashboard, moderator console, admin list).
    """
    if kind == "public":
        reply_cond = "id IN (SELECT topic_id FROM forum_replies WHERE status = 'published')"
    else:
        reply_cond = "id IN (SELECT topic_id FROM forum_replies)"
    return f"(id NOT IN (SELECT topic_id FROM curation_resource_topics WHERE kind IN ('style', 'layout')) OR id IN (SELECT topic_id FROM curation_submissions) OR {reply_cond})"


def apply_boot(db,payload,current_user):
    conn=db.get_conn()
    for w in payload.get('works', []):
        w['comments'] = []
    payload['assetComments'] = {}
    works={w['id']:w for w in payload.get('works', [])}
    assets=payload['assetComments']
    topics={t['id']:t for t in payload.get('topics', [])}
    hidden=set()
    payload['discussions']={}
    for row in conn.execute('SELECT * FROM curation_resource_topics').fetchall():
        kind,target,tid,origin=row['kind'],row['target_id'],row['topic_id'],row['origin']
        norm_target=target.upper().lstrip('#') if kind in ('style','layout') else target
        topic=topics.get(tid)
        if not topic:
            continue
        replies=topic.get('replies',[])
        raw=resolve_resource(conn,kind,norm_target)
        is_placeholder = is_resource_placeholder(conn, tid, kind)
        if kind=='work':
            if target in works:
                works[target]['comments']=replies
        else:
            assets[norm_target]=replies
            if is_placeholder and not replies:
                hidden.add(tid)
        if is_placeholder and not raw:
            hidden.add(tid)
            continue
        topic['resourceDiscussion']={'kind':kind,'targetId':norm_target,'origin':origin,'commentCount':len(replies)}
        topic['activityAtMs']=_activity(conn,replies,topic['publishedAtMs'])
        payload['discussions'][norm_target]={'topicId':tid,'count':len(replies),'origin':origin}
    payload['topics']=[t for tid,t in topics.items() if tid not in hidden]
    return payload
