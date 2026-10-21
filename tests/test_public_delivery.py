import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ops' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicDeliveryTests(unittest.TestCase):
    def test_gallery_overlay_keeps_existing_content_and_original_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = root / 'plugin'
            (plugin / 'public').mkdir(parents=True)
            (plugin / 'REVISION').write_text('a' * 40)
            for name in ('portal.js', 'portal.css', 'navigation.css', 'navigation.html', 'image-loader.js', 'discover.js', 'composer-bridge.js', 'gallery-refinement.js', 'gallery-refinement.css'):
                (plugin / 'public' / name).write_text((ROOT / 'plugin/public' / name).read_text(encoding='utf-8'), encoding='utf-8')
            (plugin / 'content').mkdir()
            (plugin / 'content/catalog.json').write_text((ROOT / 'plugin/content/catalog.json').read_text(encoding='utf-8'), encoding='utf-8')
            (plugin / 'public' / 'private.key').write_text('never publish')
            static = root / 'static'
            (static / 'gallery').mkdir(parents=True)
            original = '<html><head><script>(function() { function fixImg(img) { retryMissingURLs(); } })();</script></head><body><nav class="site-nav">Original filters</nav><img src="../../../images/layouts/SC-001.webp"><script>preview.src = card.dataset.image;</script></body></html>'
            source = static / 'gallery/layouts.html'
            source.write_text(original)
            (static / 'gallery/tutorials.html').write_text('<html><head></head><body><p>Existing composer</p></body></html>')
            (static / 'gallery' / 'private.key').write_text('never publish')
            target = root / 'output'
            load('build_public').build(plugin, target, static)
            page = (target / 'gallery/layouts.html').read_text(encoding='utf-8')
            self.assertEqual(source.read_text(), original)
            self.assertIn('data-site-section="explore" aria-current="page"', page)
            self.assertIn('Original filters', page)
            self.assertIn('https://img.handraw-style.com/images/layouts/SC-001.webp', page)
            self.assertIn('data-hw-src="https://img.handraw-style.com/images/layouts/SC-001.webp"', page)
            self.assertNotIn('<img src="https:', page)
            self.assertIn('<img src="data:image/svg+xml,', page)
            self.assertIn('/assets/image-loader.js', page)
            self.assertNotIn('retryMissingURLs', page)
            self.assertIn('HandrawImages.set(preview, card.dataset.image)', page)
            self.assertIn('/studio/assets/composer-bridge.js', (target / 'assets/composer.html').read_text(encoding='utf-8'))
            self.assertIn('data-site-section="create" aria-current="page"', (target / 'gallery/tutorials.html').read_text(encoding='utf-8'))
            self.assertFalse((target / 'assets/private.key').exists())
            self.assertFalse((target / 'gallery/private.key').exists())

    def test_static_routes_keep_missing_gallery_files_outside_the_forum(self):
        module = load('public_routes')
        original = 'server {\n    location / {\n        proxy_pass http://forum;\n    }\n}'
        public = module.configure(original, 'static')
        self.assertIn('try_files $uri =404;', public)
        self.assertIn('proxy_pass http://forum;', public)
        self.assertEqual(module.configure(public, 'static'), public)
        self.assertIn('location = /gallery/ {', public)
        self.assertIn('location = /gallery {', public)
        self.assertIn('/gallery/index.html$is_args$args;', public)
        legacy = public[0:public.index('    # handraw-gallery-entry-v1')] + public[public.index('    location ^~ /gallery/ {'):]
        self.assertEqual(module.configure(legacy, 'static'), public)
        main = module.configure(original, 'main')
        self.assertIn('return 302 https://static.handraw-style.com$uri?web=2&$args;', main)
        self.assertIn('location = /gallery/ {', main)


if __name__ == '__main__':
    unittest.main()
