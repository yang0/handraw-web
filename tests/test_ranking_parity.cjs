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
const assets = [
  { usageCount: 7, likes: 3, favorites: 2, cheers: 4, stamps: 1, tips: 2, honorBoost: 20, sourceType: 'exclusive' },
  { usageCount: 0, likes: 0, favorites: 0, cheers: 0, stamps: 0, tips: 0 },
  { usage_count: 3, likes: 15, favorites: 4, cheers: 3, stamps: 0, tips: 1 },
  { usageCount: 2, likes: 3, favorites: 4, cheers: 5, stamps: 1, tips: 2, sourceType: 'community' }
];

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
// Period and creator honor never create an independent scoring formula.
S.App.state = {
  works: [], assetCounts: { 'FA-001': 2, 'FX-001': 2 },
  assetSeedMetrics: {},
  assetLiveLikes: { 'FA-001': 3, 'FX-001': 3 },
  assetLiveFavorites: { 'FA-001': 2, 'FX-001': 2 },
  assetLiveCheers: { 'FA-001': 1, 'FX-001': 1 },
  assetLiveStamps: { 'FA-001': 0, 'FX-001': 0 },
  assetLiveTips: { 'FA-001': 1, 'FX-001': 1 },
  assetRankingWeights: { usage:10, likes:1, favorites:2, cheers:1, stamps:1, tips:2 },
  publicCreators: [{ username:'vip', honor:{ boost:999 } }]
};
S.App.styles = [
  { id:'FA-001', kind:'style', sourceType:'official', author:'vip', honorBoost:999 },
  { id:'FX-001', kind:'style', sourceType:'community', author:'ordinary', honorBoost:1 }
];
S.App.layouts = [];
assert.deepEqual(S.getRankedAssets(2, 'all').map(x => x.asset.id), ['FA-001','FX-001'],
  'equal authentic engagement means equal scoring irrespective of asset source or honor');
S.App.state.assetLiveLikes['FX-001'] = 20;
assert.equal(S.getRankedAssets(2, 'all')[0].asset.id, 'FX-001',
  'real interactions must determine ranking and override fake author honors');
assert.equal(S.getRankedAssets(2, 'all')[0].rankScore, S.popularScore('style', {
  usageCount:2, likes:20, favorites:2, cheers:1, stamps:0, tips:1
}));

console.log('Ranking parity: shared.js and backend/ranking.py agree on', works.length, 'works,', topics.length, 'topics,', assets.length, 'assets');
