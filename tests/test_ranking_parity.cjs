// 用同一组夹具，对比 shared.js 的 popularScore 与 backend/ranking.py 的 Python 结果
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

const ctx = { window:{}, URLSearchParams, clearTimeout, setTimeout, document:{}, localStorage:{getItem(){return null;},setItem(){}}, location:{search:'',pathname:'/'} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('demo/assets/shared.js','utf8'),ctx);
const S = ctx.window.HANDRAW_SHARED;

const works = [
  { likes: 0, cheers: 0, favorites: 0, forks: 0 },
  { likes: 1, cheers: 2, favorites: 3, forks: 4 },
  { likes: 10, cheers: 0, favorites: 0, forks: 0 },
  { likes: 0, cheers: 0, favorites: 0, forks: 5 },
  { likes: 7, cheers: 3, favorites: 1, forks: 2 },
];
const topics = [
  { likes: 1, favorites: 2, replies: [{}, {}] },
  { likes: 0, favorites: 0, replies: [] },
  { likes: 5, favorites: 0, replyCount: 3 },
];
const assets = [{ usageCount: 7 }, { usageCount: 0 }];

const jsWork = works.map(w => S.popularScore('work', w));
const jsTopic = topics.map(t => S.popularScore('topic', t));
const jsAsset = assets.map(a => S.popularScore('style', a));

const py = JSON.parse(execFileSync('python', ['-X','utf8','-c', `
import sys, json
sys.path.insert(0, '.')
from backend.ranking import work_popular_score, topic_popular_score, asset_popular_score
works = json.loads(sys.argv[1]); topics = json.loads(sys.argv[2]); assets = json.loads(sys.argv[3])
print(json.dumps({
  'work': [work_popular_score(w) for w in works],
  'topic': [topic_popular_score(t) for t in topics],
  'asset': [asset_popular_score(a) for a in assets],
}))
`, JSON.stringify(works), JSON.stringify(topics), JSON.stringify(assets)], {encoding:'utf8'}));

assert.deepEqual(jsWork, py.work, 'work popularity must match between shared.js and ranking.py');
assert.deepEqual(jsTopic, py.topic, 'topic popularity must match');
assert.deepEqual(jsAsset, py.asset, 'asset popularity must match');
console.log('Ranking parity: shared.js and backend/ranking.py agree on', works.length, 'works,', topics.length, 'topics,', assets.length, 'assets');
