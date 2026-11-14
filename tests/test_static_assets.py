import hashlib
import re
import tempfile
import unittest
from pathlib import Path

from backend.static_assets import version_frontend_html


class AssetIdentityTests(unittest.TestCase):
    def test_preload_and_script_share_content_identity_and_change_with_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            asset = root / "assets/app.js"
            asset.write_bytes(b"first")
            (root / "assets/theme.css").write_bytes(b"paper")
            page = b"""<link rel="preload" href="/assets/app.js?v=1" as="script">
<script src="/assets/app.js?v=999"></script><link href='/assets/theme.css'>"""
            result = version_frontend_html(page, root)
            versions = re.findall(rb"app.js\?v=([a-f0-9]+)", result)
            self.assertEqual(
                versions, [hashlib.sha256(b"first").hexdigest()[:24].encode()] * 2
            )
            self.assertRegex(result, rb"theme.css\?v=[a-f0-9]{24}")
            asset.write_bytes(b"other")
            self.assertNotEqual(version_frontend_html(page, root), result)
            self.assertEqual(
                version_frontend_html(result, root), version_frontend_html(page, root)
            )

    def test_nonlocal_missing_and_traversal_untouched_and_query_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            (root / "assets/a.js").write_bytes(b"ok")
            page = b"""<script src="https://example.com/assets/a.js?v=1"></script>
<script src="/assets/missing.js?v=1"></script><img src="/assets/a.js?v=1">
<script src="/assets/../../outside.js?v=1"></script>"""
            self.assertEqual(version_frontend_html(page, root), page)
            result = version_frontend_html(
                b'<script src="/assets/a.js?x=1&amp;v=2&amp;empty=#anchor"></script>',
                root,
            )
            self.assertIn(b"?x=1&amp;empty=&amp;v=", result)
            self.assertIn(b"#anchor", result)


if __name__ == "__main__":
    unittest.main()
