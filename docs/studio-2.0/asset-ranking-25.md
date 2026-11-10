# #25 · Resource popularity source of truth

2026-11-09 · Web branch: studio2-issue25-asset-ranking-20261109. No production release decision is implied.

## Formula and consistent scope

`backend/ranking.py` defines the only weight schedule: `usage*10 + likes + 2*favorites + cheers + stamps + 2*tips`. SQL on aggregated metrics uses `asset_popular_sql`, Python uses `asset_popular_score`; the browser reads `assetRankingWeights` from `/api/boot` and uses `popularScore('style'|'layout', normalizedMetrics)`. The bundled browser fallback is for demo/offline and is pinned by actual Node ↔ Python parity tests. Distinct sources (community, official, exclusive) receive **no hidden popularity multiplier**, author honours do not affect resource ranking, and no time-decay bonus applies.

Sources and units:
- `usageCount`: number of publicly published Works referencing a style/layout (not total media count; one logical work counted once per asset). The week/month tabs narrow this usage count to Works created in the selected period; engagement stats have no equivalent audited period query and remain lifetime values.
- `likes`: `interactions` `like_style` / `like_layout`, one record per user/resource.
- `favorites`: `collections` in `styles` or `layouts`, one record per user/resource.
- `cheers`: `interactions` with `target_type='asset'`, `stamp_label=''`; includes tip-associated encouragement when present, matching user-visible interactions.
- `stamps`: historical `interactions` `target_type='asset'` with nonempty `stamp_label`; the API has retired *creating new stamps*, but historical counts remain valid.
- `tips`: **count of accepted `tip_requests`** with `target_type='asset'`; *not* amount of credits transferred. It does not use cached `catalog_assets.tips` or inflated `catalog_assets.cheers` (+3 per tip).

All keys use normalized uppercase resource IDs. The server's `assetSeedMetrics` remains demo-only and is never used to fill actual production popularity. `/api/boot` adds `assetLiveCheers`, `assetLiveStamps`, `assetLiveTips` and `assetRankingWeights` alongside the existing likes/favorites maps, preserving older client fields. Interactions are aggregated once in SQL, rather than N per-item round trips; no database schema migration or sensitive definition export is necessary.

## Delivery and regression

- `tests/test_ranking.py`: canonical score / SQL expression consistency / honours ignored.
- `tests/test_ranking_parity.cjs`: Python vs browser fixture parity; actual `getRankedAssets` reflects interaction scores and not author/source boosts.
- `tests/test_asset_ranking_25.py`: real SQLite boot aggregation with one official code and one community code; zero-score non-fabrication.
- `.github/workflows/checks.yml` wires the Node parity script into the existing `feed-ui-regression` job; Python full six shards discover Python tests automatically. The 14 required jobs stay unchanged.

Issue closure requires branch CI 14/14; non-force/expected SHA fast-forward to `studio2`, then Push + Draft PR #131 CI 14/14. No `main` modifications.
