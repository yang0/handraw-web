"""Refresh the public resource snapshot from a checked-out official Skill."""
import argparse
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('skill', type=Path, help='Path to skills/handdraw-style-prompter')
args = parser.parse_args()
references = args.skill / 'references'
styles, layouts, colors = [json.loads((references / f'{kind}.json').read_text(encoding='utf-8')) for kind in ('styles', 'layouts', 'colors')]
legacy = dict(re.findall(r'data-number="([A-Z]+-\d+)"[^>]*data-legacy="(\d+)"', (args.skill / 'gallery/index.html').read_text(encoding='utf-8')))
resources = []
for item in styles:
    number = item['number']
    definition = f"#{number} {item['generation_name']}。参考作者/风格名称：{item.get('reference', item.get('ref', ''))}。核心风格特征：{item['traits']}。"
    resources.append({'id': number, 'legacy': legacy.get(number, ''), 'kind': 'style', 'name': item['generation_name'], 'group': item['group'], 'description': item['traits'], 'definition': definition, 'image': f'https://img.handraw-style.com/images/individual/{number.split("-")[0]}/{number}.webp'})
for item in layouts:
    prompt = references / item['prompt_file']
    resources.append({'id': item['id'], 'kind': 'layout', 'name': item['name'], 'group': item['category'], 'description': '、'.join(item.get('keywords', [])), 'definition': prompt.read_text(encoding='utf-8') if prompt.exists() else '', 'image': item['image'].replace('../../../images/', 'https://img.handraw-style.com/images/')})
for item in colors:
    resources.append({'id': item['id'], 'kind': 'color', 'name': item['name_zh'], 'group': item['category_zh'], 'description': item['quote_zh'], 'definition': item['prompt_zh'], 'image': item['image'].replace('../../../images/', 'https://img.handraw-style.com/images/')})
target = Path(__file__).resolve().parents[1] / 'plugin/content'
editorial = json.loads((target / 'editorial.json').read_text(encoding='utf-8'))
index = {item['id']: item for item in resources}
for item in editorial['featured']:
    if item['id'] not in index:
        raise SystemExit(f'Featured resource is missing: {item["id"]}; no content was written.')
for item in editorial['featured']:
    item.update(index[item['id']])
for item in editorial.get('featured_layouts', []):
    item.update(index[item['id']])
counts = {'style': len(styles), 'layout': len(layouts), 'color': len(colors)}
editorial['counts'] = counts
(target / 'catalog.json').write_text(json.dumps({'version': 1, 'source': 'yang0/handraw-style official references', 'counts': counts, 'resources': resources}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
(target / 'editorial.json').write_text(json.dumps(editorial, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Refreshed {len(resources)} official resources. Existing editorial titles, guides and templates retained.')
