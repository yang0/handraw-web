"""#84/#112 deterministic ownership, multi-image, moderation audit contracts."""
import copy
import unittest

from ops.audit_v3_cross_client_84_112 import audit_v3_uploads


def fixture():
    specs = [
        {"owner": "owner-A", "client": "web", "run": "run-A",
         "work": "work-A", "successful": 3, "totalSlots": 5, "status": "public"},
        {"owner": "owner-B", "client": "skill", "run": "run-B",
         "work": "work-B", "successful": 5, "totalSlots": 5, "status": "public"},
        {"owner": "owner-A", "client": "skill", "run": "run-C",
         "work": "work-C", "successful": 1, "totalSlots": 1, "status": "hidden"},
    ]
    rows = []
    for spec in specs:
        positions = [0, 2, 4] if spec["run"] == "run-A" else list(range(spec["successful"]))
        for i in positions:
            media = f'{spec["run"]}-media-{i}'
            rows.append({
                "owner": spec["owner"], "client": spec["client"],
                "run": spec["run"], "work": spec["work"],
                "position": i, "media": media, "mediaOwner": spec["owner"],
                "workMedia": media, "publicGrant": spec["status"] == "public",
            })
    return rows, specs


class CrossClientV3Audit(unittest.TestCase):
    def test_web_partial_success_skill_five_and_hidden_work(self):
        rows, specs = fixture()
        report = audit_v3_uploads(rows, specs)
        self.assertEqual(report["auditedRuns"], 3)
        self.assertEqual(report["auditedSuccessfulMedia"], 9)
        self.assertEqual(report["owners"], 2)
        self.assertTrue(report["crossOwnerIsolation"])
        self.assertFalse(report["readyForRelease"])
        self.assertTrue(report["productionNoGo"])

    def test_foreign_media_or_work_link_rejected(self):
        for field, value in (("mediaOwner", "owner-B"), ("workMedia", "other-media"),
                             ("work", "work-B"), ("client", "skill")):
            with self.subTest(field=field):
                rows, specs = fixture()
                rows[0][field] = value
                with self.assertRaises(ValueError):
                    audit_v3_uploads(rows, specs)

    def test_duplicate_slot_or_missing_image_rejected(self):
        rows, specs = fixture()
        with self.assertRaises(ValueError):
            audit_v3_uploads(rows + [copy.deepcopy(rows[0])], specs)
        with self.assertRaises(ValueError):
            audit_v3_uploads(rows[:-1], specs)

    def test_missing_grant_and_hidden_grant_rejected(self):
        for index, value in ((0, False), (-1, True)):
            rows, specs = fixture()
            rows[index]["publicGrant"] = value
            with self.assertRaises(ValueError):
                audit_v3_uploads(rows, specs)

    def test_cross_owner_duplicate_media_and_run_rejected(self):
        rows, specs = fixture()
        rows[3]["media"] = rows[0]["media"]
        rows[3]["workMedia"] = rows[0]["media"]
        with self.assertRaises(ValueError):
            audit_v3_uploads(rows, specs)
        rows, specs = fixture()
        specs[1]["run"] = specs[0]["run"]
        rows[3]["run"] = specs[0]["run"]
        with self.assertRaises(ValueError):
            audit_v3_uploads(rows, specs)

    def test_invalid_position_or_out_of_bounds_rejected(self):
        for position in (-1, 5, "2"):
            rows, specs = fixture()
            rows[0]["position"] = position
            with self.assertRaises(ValueError):
                audit_v3_uploads(rows, specs)


if __name__ == "__main__":
    unittest.main()
