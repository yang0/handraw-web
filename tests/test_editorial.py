import json
import unittest
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[1]


class EditorialContentTests(unittest.TestCase):
    def test_catalog_and_home_counts_reference_the_same_real_resources(self):
        catalog = json.loads((ROOT / 'plugin/content/catalog.json').read_text(encoding='utf-8'))
        editorial = json.loads((ROOT / 'plugin/content/editorial.json').read_text(encoding='utf-8'))
        counts = dict(Counter(item['kind'] for item in catalog['resources']))
        self.assertEqual(catalog['counts'], counts)
        self.assertEqual(editorial['counts'], counts)
        resources = {item['id']: item for item in catalog['resources']}
        self.assertEqual(len(resources), len(catalog['resources']))
        for item in editorial['featured']:
            self.assertIn(item['id'], resources)
            self.assertEqual(item['image'], resources[item['id']]['image'])
            self.assertEqual(urlparse(item['image']).hostname, 'img.handraw-style.com')
        for template in editorial['templates']:
            for field in ('style', 'layout', 'color'):
                if template[field]:
                    self.assertEqual(resources[template[field]]['kind'], field)
        self.assertGreaterEqual(len(editorial['featured']), 8)
        self.assertGreaterEqual(len(editorial['guides']), 5)
        self.assertTrue(all(len(guide['steps']) >= 3 for guide in editorial['guides']))

    def test_legacy_style_numbers_resolve_without_collisions(self):
        catalog = json.loads((ROOT / 'plugin/content/catalog.json').read_text(encoding='utf-8'))
        aliases = [item['legacy'] for item in catalog['resources'] if item['kind'] == 'style' and item.get('legacy')]
        self.assertEqual(len(aliases), len(set(aliases)))
        self.assertEqual(next(item['id'] for item in catalog['resources'] if item.get('legacy') == '001'), 'FA-001')


if __name__ == '__main__':
    unittest.main()
