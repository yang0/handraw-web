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
    row=conn.execute('SELECT * FROM catalog_assets WHERE code=? AND kind=?',(target,kind)).fetchone()
    if row:
        return dict(row) if row['status']=='published' and (S.is_demo_mode() or target not in S.seed_ids('assets')) else None
    item=static_catalog().get(target)
    return item if item and item['kind']==kind else None


def ensure_topic(tx,kind,target,resource):
    row=tx.execute('SELECT topic_id FROM curation_resource_topics WHERE kind=? AND target_id=?',(kind,target)).fetchone()
    if row:
        return row['topic_id']
    tid='topic_'+uuid.uuid4().hex
    label={'style':'画风','layout':'图型','work':'作品'}[kind]
    name=resource.get('name') or resource.get('title') or target
    if not re.search(r'[\u3400-\u9fff]',name):
        chinese=re.split(r'[、，,。；;]',str(resource.get('description') or ''))[0].strip()
        name=chinese[:18] if re.search(r'[\u3400-\u9fff]',chinese) else label
    images=json.loads(resource.get('images_json') or '[]') if kind=='work' else [resource.get('image_url') or resource.get('image')]
    images=[sanitize_media_url(i.get('url','') if isinstance(i,dict) else str(i or '')) for i in images]
    images=[i for i in images if i][:9]
    now=S.utc_now_iso()
    tx.execute("INSERT INTO forum_topics (id,category,category_label,title,author_username,author_name,summary,images_json,styles_json,layout_code,work_id,status,published_at_ms,created_label,created_at,updated_at) VALUES (?,'assets','画风与图型专区',?,'','资源讨论',?,?,?,?,?,'published',?,'刚刚',?,?)",(tid,f'{name} · {label}讨论',f'围绕这项{label}交流使用心得。',json.dumps(images,ensure_ascii=False),json.dumps([target] if kind=='style' else []),target if kind=='layout' else '',target if kind=='work' else '',int(time.time()*1000),now,now))
    origin='official' if kind!='work' and resource.get('source_type','official')!='community' else 'legacy'
    tx.execute('INSERT INTO curation_resource_topics (kind,target_id,topic_id,origin,created_at) VALUES (?,?,?,?,?)',(kind,target,tid,origin,now))
    return tid


def comment(db,user,kind,target_id,text):
    target=str(target_id).strip().upper().lstrip('#') if kind!='work' else str(target_id).strip()
    clean=sanitize_html(str(text or '').strip())[:800]
    if not clean:
        raise S.ServiceError('请输入评论内容')
    conn=db.get_conn()
    mapping=conn.execute('SELECT * FROM curation_resource_topics WHERE kind=? AND target_id=?',(kind,target)).fetchone()
    if mapping and mapping['origin']=='submission':
        result=S.publish_forum_reply_post(db,user,mapping['topic_id'],clean)
        result['topicId']=mapping['topic_id']
        result['comment']={'id':result['replyId'],'user':user['username'],'name':user['display_name'],'text':clean,'time':'刚刚'}
        return result
    with db.transaction() as tx:
        resource=resolve_resource(tx,kind,target)
        if not resource:
            raise S.ServiceError('资源不存在或尚未收录',status=404)
        tid=ensure_topic(tx,kind,target,resource)
        topic=tx.execute('SELECT status FROM forum_topics WHERE id=?',(tid,)).fetchone()
        if not topic or topic['status']!='published':
            raise S.ServiceError('讨论已暂停',status=409)
        cid=('wc_' if kind=='work' else 'ac_')+uuid.uuid4().hex
        now=S.utc_now_iso()
        if kind=='work':
            tx.execute("INSERT INTO work_comments (id,work_id,author_username,author_name,text,status,time_label,created_at) VALUES (?,?,?,?,?,'published','刚刚',?)",(cid,target,user['username'],user['display_name'],clean,now))
        else:
            tx.execute("INSERT INTO asset_comments (id,asset_code,asset_kind,author_username,author_name,text,status,time_label,created_at) VALUES (?,?,?,?,?,?,'published','刚刚',?)",(cid,target,kind,user['username'],user['display_name'],clean,now))
    return {'ok':True,'topicId':tid,'replyId':cid,'assetCode':target if kind!='work' else None,'assetKind':kind,'comment':{'id':cid,'user':user['username'],'name':user['display_name'],'text':clean,'time':'刚刚'}}


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


def apply_boot(db,payload,current_user):
    conn=db.get_conn()
    works={w['id']:w for w in payload['works']}
    assets=payload['assetComments']
    # A GET must never create storage.  Legacy resources used to get a lazily
    # created discussion topic here, which meant every /api/boot call opened a
    # write transaction on the hottest read path (and contradicted the module's
    # own "no GET creates storage" contract).  Any topic a legacy resource does
    # own already exists in curation_resource_topics, so the loop below finds it
    # without being told about it first.
    topics={t['id']:t for t in payload['topics']}
    hidden=set()
    payload['discussions']={}
    for row in conn.execute('SELECT * FROM curation_resource_topics').fetchall():
        kind,target,tid,origin=row['kind'],row['target_id'],row['topic_id'],row['origin']
        topic=topics.get(tid)
        if origin=='submission':
            if topic:
                replies=topic['replies']
                if kind=='work' and target in works:
                    works[target]['comments']=replies
                elif kind!='work':
                    assets[target]=replies
                payload['discussions'][target]={'topicId':tid,'count':len(replies),'origin':origin}
                topic['activityAtMs']=_activity(conn,replies,topic['publishedAtMs'])
            continue
        replies=works.get(target,{}).get('comments',[]) if kind=='work' else assets.get(target,[])
        if not replies or not resolve_resource(conn,kind,target):
            hidden.add(tid)
            continue
        if not topic:
            raw=conn.execute("SELECT * FROM forum_topics WHERE id=? AND status='published'",(tid,)).fetchone()
            if not raw:
                continue
            topic=S._serialize_topic(raw,{tid:replies},set(payload.get('unlockedIds',[])),current_user)
            topics[tid]=topic
        topic['replies']=[dict(r,likes=int(r.get('likes') or 0),accepted=bool(r.get('accepted'))) for r in replies]
        topic['resourceDiscussion']={'kind':kind,'targetId':target,'origin':origin,'commentCount':len(replies)}
        topic['activityAtMs']=_activity(conn,replies,topic['publishedAtMs'])
        payload['discussions'][target]={'topicId':tid,'count':len(replies),'origin':origin}
    payload['topics']=[t for tid,t in topics.items() if tid not in hidden]
    return payload
