"""Issue #123: reject invalid or unauthorized references before billable reserve.

The owner-scoped image resolver is injected so tests cannot accidentally load
any user content or send a billable gateway request.
"""
import unittest
from pathlib import Path
from backend.server import preflight_generation_references
from backend.services import ServiceError


class SeriesReferencePreflightTests(unittest.TestCase):
    def test_accessible_references_resolved_exactly_once(self):
        seen=[]
        def authorized(path):
            seen.append(path)
            return {"b64_json":"AAAA", "mime_type":"image/png"}
        result=preflight_generation_references({
            "customRefImg":"/uploads/owned.png",
            "refImages":["/generated/owned.webp","data:image/png;base64,AAAA"]
        },authorized)
        self.assertEqual(len(result),3)
        self.assertEqual(seen,[
            "/uploads/owned.png","/generated/owned.webp",
            "data:image/png;base64,AAAA"
        ])

    def test_private_or_deleted_ref_is_forbidden_before_reservation(self):
        seen=[]
        def owner_resolver(path):
            seen.append(path)
            return {"b64_json":"AAAA"} if path=="/uploads/owned.png" else None
        with self.assertRaises(ServiceError) as ctx:
            preflight_generation_references({
                "refImages":["/uploads/owned.png", "/generated/other-user.webp"]
            },owner_resolver)
        self.assertEqual(ctx.exception.status,403)
        self.assertEqual(ctx.exception.code,"generation_reference_forbidden")
        self.assertEqual(seen,["/uploads/owned.png","/generated/other-user.webp"])

    def test_invalid_uploads_and_over_limit_reject(self):
        for body in (
            {"refImages":["blob:local"]},
            {"refImages":[None]},
            {"refImages":["/uploads/a.png"]*7},
            {"refImages":"not-an-array"},
        ):
            with self.subTest(body=body), self.assertRaises(ServiceError):
                preflight_generation_references(body, lambda _:None)

    def test_writes_do_not_resolve_from_nonexistent_url(self):
        # The helper remains a pure read/validation boundary. The production
        # handler invokes it before prepare_cloud_generation and uses decoded
        # bytes once for all candidate attempts.
        app=Path("backend/server.py").read_text(encoding="utf-8")
        start=app.index('if req_path == "/api/studio/generate":')
        submit=app[start: start+1600]
        self.assertLess(submit.index("preflight_generation_references("),
                        submit.index("prepare_cloud_generation(self.db"))
        self.assertIn("refs.extend(validated_refs)",app)


if __name__=="__main__":
    unittest.main()
