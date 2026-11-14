"""Internal Meilisearch client; mutations are complete only after task success."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .services import ServiceError


class SearchEngine:
    def __init__(self, *, write=False):
        self.url = os.environ.get('HANDRAW_SEARCH_URL', 'http://127.0.0.1:7700').rstrip('/')
        self.key = os.environ.get('HANDRAW_SEARCH_WRITE_KEY' if write else 'HANDRAW_SEARCH_KEY', '')
        if not self.key:
            raise ServiceError('全文搜索暂不可用，请稍后重试', 503, 'search_unavailable')

    def request(self, method, path, data=None, *, timeout=10):
        req = urllib.request.Request(self.url + path,
            data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
            method=method, headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, ValueError, OSError) as exc:
            # Never expose engine URLs, key material or source documents in errors.
            raise ServiceError('全文搜索服务暂不可用', 503, 'search_unavailable') from exc

    def wait(self, task, *, timeout=180):
        uid = task['taskUid'] if isinstance(task, dict) else task
        until = time.monotonic() + timeout
        delay = .01
        while time.monotonic() < until:
            state = self.request('GET', f'/tasks/{int(uid)}')
            if state['status'] == 'succeeded':
                return state
            if state['status'] in ('failed', 'canceled'):
                code = (state.get('error') or {}).get('code', 'index_task_failed')
                raise RuntimeError(f'Search task {uid} failed ({code})')
            time.sleep(delay)
            delay = min(.1, delay * 2)
        raise TimeoutError(f'Search task {uid} still pending')

    def ensure_index(self, index):
        # Listing is intentional: do not mistake an unavailable engine for a missing index.
        indexes = self.request('GET', '/indexes?limit=1000')['results']
        if any(item['uid'] == index for item in indexes):
            return False
        self.wait(self.request('POST', '/indexes', {'uid': index, 'primaryKey': 'id'}))
        self.wait(self.request('PATCH', f'/indexes/{index}/settings', {
            'rankingRules': ['words', 'sort', 'typo', 'proximity', 'attribute', 'exactness'],
            'searchableAttributes': ['code','title','aliases','tags','author','body'],
            'displayedAttributes': ['*'], 'filterableAttributes': ['board','result_id','code'],
            'sortableAttributes': ['published'], 'distinctAttribute': 'result_id',
            'pagination': {'maxTotalHits': 2000},
            'typoTolerance': {'disableOnAttributes': ['code']},
            'synonyms': {'国风':['中国风'], '中国风':['国风'], '水彩':['watercolor'],
                         'watercolor':['水彩'], '电商':['ecommerce'], 'ecommerce':['电商']},
        }))
        return True

    def replace_entity(self, index, root, docs):
        self.wait(self.request('POST', f'/indexes/{index}/documents/delete', {'filter': 'result_id = ' + json.dumps(root)}))
        for start in range(0, len(docs), 64):
            self.wait(self.request('POST', f'/indexes/{index}/documents', docs[start:start+64]))


def index_name(channel):
    return 'handraw_' + channel
