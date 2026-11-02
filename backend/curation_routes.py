"""Authenticated routes for community collection; all private responses are no-store."""
import json
import re
import time
import uuid

from . import curation as C
from .services import ServiceError, utc_now_iso


def _media(handler,user,payload):
    from .server import validate_publish_media
    if not isinstance(payload,dict):
        raise ServiceError('投稿格式错误')
    if 'images' in payload and not isinstance(payload['images'],list):
        raise ServiceError('图片必须以列表提交')
    clean=validate_publish_media(handler.db,user,payload)
    # Validation may discard foreign media. Do not publish a partially changed item silently.
    if (
        len(clean.get('images',[]))!=len(payload.get('images',[]))
        or (payload.get('image') and not clean.get('image'))
        or (payload.get('cover') and not clean.get('cover'))
    ):
        raise ServiceError('图片不存在或不属于当前账号',status=403)
    return clean


def _grant(handler,user,result):
    from .server import _grant_published_media
    tid=result.get('topicId')
    if not tid:
        return
    row=handler.db.get_conn().execute('SELECT images_json FROM forum_topics WHERE id=? AND author_username=?',(tid,user['username'])).fetchone()
    if row:
        _grant_published_media(handler.db,user,{'images':json.loads(row['images_json'])},target_type='topic',target_id=tid)


def handle_get(handler,path,qs):
    if not path.startswith('/api/curation/'):
        return False
    user=handler._current_user(required=True)
    actions={'/api/curation/mine':C.my_submissions,'/api/curation/access':C.review_access,'/api/curation/review-queue':C.review_queue,'/api/curation/admin':C.admin_overview}
    if path in actions:
        handler._send_json(actions[path](handler.db,user))
        return True
    match=re.fullmatch(r'/api/curation/drafts/([a-f0-9]{32})',path)
    if match:
        row=handler.db.get_conn().execute('SELECT payload_json FROM curation_drafts WHERE id=? AND owner_user_id=? AND expires_at>?',(match[1],user['id'],time.time())).fetchone()
        if not row:
            raise ServiceError('草稿不存在或已过期',status=404)
        handler._send_json({'ok':True,'payload':json.loads(row[0])})
        return True
    raise ServiceError('接口不存在',status=404)


def handle_post(handler,path,body):
    if not path.startswith('/api/curation/'):
        return False
    user=handler._current_user(required=True)
    db=handler.db
    if path=='/api/curation/drafts':
        payload=body.get('payload',body)
        if not isinstance(payload,dict):
            raise ServiceError('草稿格式错误')
        items=payload.get('items')
        if items is not None:
            if not isinstance(items,list) or len(items)>20:
                raise ServiceError('草稿项目过多')
            payload=dict(payload,items=[_media(handler,user,i) for i in items])
        else:
            payload=_media(handler,user,payload)
        encoded=json.dumps(payload,ensure_ascii=False)
        if len(encoded)>500000:
            raise ServiceError('草稿内容过大')
        draft_id=uuid.uuid4().hex
        with db.transaction() as tx:
            tx.execute('DELETE FROM curation_drafts WHERE expires_at<?',(time.time(),))
            tx.execute('INSERT INTO curation_drafts (id,owner_user_id,payload_json,expires_at,created_at) VALUES (?,?,?,?,?)',(draft_id,user['id'],encoded,time.time()+1800,utc_now_iso()))
        result={'ok':True,'id':draft_id}
    elif path=='/api/curation/submissions':
        items=body.get('items')
        if not isinstance(items,list) or not items:
            raise ServiceError('请至少提交一项内容',status=400,code='missing_items')
        if len(items)!=1:
            raise ServiceError('每次投稿只能提交一个画风或一个图型。',status=400,code='single_item_only')
        it0 = items[0] if isinstance(items[0], dict) else {}
        label = "画风" if it0.get("kind") == "style" else "图型"
        desc_val = str(it0.get("description") or it0.get("notes") or body.get("text") or "").strip()[:300]
        desc_non_ws = re.sub(r"\s+", "", desc_val)
        if not desc_non_ws:
            raise ServiceError(f"请填写{label}简介", status=400, code="missing_description")
        if len(desc_non_ws) < 8:
            raise ServiceError(f"{label}简介至少需要 8 个字", status=400, code="description_too_short")
        clean=dict(body,items=[_media(handler,user,i) for i in items])
        result=C.submit(db,user,clean)
        _grant(handler,user,result)
    elif path=='/api/curation/votes':
        result=C.vote(db,user,body)
    elif path=='/api/curation/access':
        result=C.grant_access(db,user,body)
    elif path=='/api/curation/admin/review':
        result=C.admin_review(db,user,body)
    else:
        match=re.fullmatch(r'/api/curation/submissions/([a-f0-9]{32})/(revise|appeal)',path)
        if not match:
            raise ServiceError('接口不存在',status=404)
        if match[2]=='revise':
            result=C.revise(db,user,match[1],{'payload':_media(handler,user,body.get('payload'))})
            _grant(handler,user,result)
        else:
            result=C.appeal(db,user,match[1],body.get('reason',''))
    handler._send_json(result)
    return True
