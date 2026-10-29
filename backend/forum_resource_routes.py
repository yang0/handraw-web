"""Forum resource endpoints; authentication and origin checks stay in the server."""
import re
from . import forum_resources as R
from .services import ServiceError


def _match(path):
    if not path.startswith('/api/forum/resources/'):
        return None
    found=re.fullmatch(r'/api/forum/resources/(style|layout|work|asset)/([^/]+)(?:/(related|comments))?',path)
    if not found:
        raise ServiceError('接口不存在',status=404)
    return found.groups()


def handle_get(handler,path,qs):
    legacy=re.fullmatch(r'/api/forum/resource-topics/([^/]+)',path)
    if legacy:
        rows=handler.db.get_conn().execute('SELECT kind,target_id FROM curation_resource_topics WHERE topic_id=? ORDER BY kind,target_id',(legacy[1],)).fetchall()
        topic=handler.db.get_conn().execute('SELECT status FROM forum_topics WHERE id=?',(legacy[1],)).fetchone()
        if not rows or not topic or topic['status']!='published':
            raise ServiceError('讨论不存在',status=404)
        user=handler._current_user(required=False)
        for row in rows:
            try:
                kind,target,*_=R._context(handler.db,user,row['kind'],row['target_id'])
                handler._send_json({'ok':True,'kind':kind,'id':target})
                return True
            except ServiceError:
                continue
        raise ServiceError('资源不存在',status=404)
    route=_match(path)
    if not route:
        return False
    kind,target,suffix=route
    user=handler._current_user(required=False)
    def value(key,default=''):
        return qs.get(key,[default])[0]
    if suffix=='related':
        result=R.related_items(handler.db,user,kind,target,value('tab','works'),value('q'),value('sort','newest'),value('offset',0),value('limit',24))
    elif suffix=='comments':
        result=R.resource_comments(handler.db,user,kind,target,value('offset',0),value('limit',20))
    else:
        result=R.resource_detail(handler.db,user,kind,target)
    handler._send_json(result)
    return True


def handle_post(handler,path,body):
    route=_match(path)
    if not route:
        return False
    kind,target,suffix=route
    if suffix!='comments':
        raise ServiceError('接口不存在',status=404)
    user=handler._current_user(required=True)
    handler._send_json(R.post_comment(handler.db,user,kind,target,body.get('text','')))
    return True
