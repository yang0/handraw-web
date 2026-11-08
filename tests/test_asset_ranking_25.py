"""Issue #25: authoritative resource interactions are identical for official and community codes."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.db import Database
from backend.services import build_boot_payload, register_user
from backend.ranking import ASSET_POPULAR_WEIGHTS, asset_popular_score


class AssetRankingBoot25(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rank25-")
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.addCleanup(self.db.close)
        self.db.migrate()
        user, _ = register_user(self.db, "rank25_owner", "StrongPassword123!")
        self.user = user
        self.uid = int(user["id"])

    def test_official_and_community_use_identical_event_counting(self):
        for code in ("FA-035", "USR-S987"):
            with self.db.transaction() as tx:
                tx.execute(
                    "INSERT INTO interactions (user_id,target_type,target_id,stamp_label,created_at)"
                    " VALUES (?,?,?,'','2026-11-09T00:00:00Z')",
                    (self.uid, "asset", code),
                )
                # A historical stamp may remain, while new stamp endpoints reject creation.
                tx.execute(
                    "INSERT INTO interactions (user_id,target_type,target_id,stamp_label,created_at)"
                    " VALUES (?,?,?,'历史印章','2026-11-09T00:00:01Z')",
                    (self.uid, "asset", code),
                )
                tx.execute(
                    "INSERT INTO interactions (user_id,target_type,target_id,stamp_label,created_at)"
                    " VALUES (?,?,?,'','2026-11-09T00:00:02Z')",
                    (self.uid, "like_style", code),
                )
                tx.execute(
                    "INSERT INTO collections (user_id,bucket,target_id,created_at)"
                    " VALUES (?,'styles',?,'2026-11-09T00:00:00Z')",
                    (self.uid, code),
                )
                tx.execute(
                    "INSERT INTO tip_requests (user_id,request_id,target_type,target_id,amount,created_at)"
                    " VALUES (?,?, 'asset',?,5,'2026-11-09T00:00:02Z')",
                    (self.uid, "rank25_tip_"+code, code),
                )
        data = build_boot_payload(self.db, None)
        self.assertEqual(data["assetRankingWeights"], ASSET_POPULAR_WEIGHTS)
        for code in ("FA-035", "USR-S987"):
            self.assertEqual(data["assetLiveCheers"][code], 1)
            self.assertEqual(data["assetLiveStamps"][code], 1)
            self.assertEqual(data["assetLiveTips"][code], 1)
            self.assertEqual(data["assetLiveLikes"][code], 1)
            self.assertEqual(data["assetLiveFavorites"][code], 1)
            self.assertEqual(
                asset_popular_score({
                    "usageCount":0, "likes":data["assetLiveLikes"][code],
                    "favorites":data["assetLiveFavorites"][code],
                    "cheers":data["assetLiveCheers"][code],
                    "stamps":data["assetLiveStamps"][code],
                    "tips":data["assetLiveTips"][code],
                }), 7
            )

    def test_absent_asset_events_never_invent_baselines(self):
        data = build_boot_payload(self.db, None)
        self.assertEqual(data["assetLiveCheers"].get("FA-035", 0), 0)
        self.assertEqual(data["assetLiveStamps"].get("FA-035", 0), 0)
        self.assertEqual(data["assetLiveTips"].get("FA-035", 0), 0)
        self.assertEqual(asset_popular_score({"usageCount":0}), 0)


if __name__ == "__main__":
    unittest.main()
