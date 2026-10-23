"""Version the public Skill's assembler command and controls without personal libraries."""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('skill', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = (args.skill / 'gallery/tutorials.html').read_text(encoding='utf-8')
references = args.skill / 'references'

class Presets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = {name: [] for name in ('modes', 'ratios', 'moods', 'shoot_types')}
        self.button = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'button':
            for key, group in [('data-mode', 'modes'), ('data-ratio', 'ratios'), ('data-mood-zh', 'moods'), ('data-type-zh', 'shoot_types')]:
                if key in attrs:
                    self.button = {'value': attrs[key], 'label': ''}
                    self.items[group].append(self.button)
                    break
    def handle_data(self, data):
        if self.button is not None:
            self.button['label'] += data.strip()
    def handle_endtag(self, tag):
        if tag == 'button':
            self.button = None

presets = Presets()
presets.feed(source)
module_spec = importlib.util.spec_from_file_location('official_reference_policy', args.skill / 'scripts/resolve_reference.py')
sys.path.insert(0, str((args.skill / 'scripts').resolve()))
resolver = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(resolver)
policy = resolver.load_policy()
style_policy = {}
for style in json.loads((references / 'styles.json').read_text(encoding='utf-8')):
    decision = resolver.resolve('gpt-image-2', style['number'], policy)
    definition = f"风格名称：{style['generation_name']}。参考作者/风格名称：{style.get('reference', '')}。"
    if decision['prompt_traits']:
        definition += f"核心风格特征：{decision['prompt_traits']}。"
    reference = decision['reference_path']
    if reference:
        reference = Path(reference).resolve().relative_to(args.skill.parents[1].resolve()).as_posix()
    style_policy[style['number']] = {'definition': definition, 'reference': reference}

options = {'source': 'yang0/handraw-style:gallery/tutorials.html',
           'source_sha256': hashlib.sha256(source.encode()).hexdigest(), **presets.items,
           'tones': json.loads((references / 'tones.json').read_text(encoding='utf-8')),
           'assets': json.loads((references / 'characters.json').read_text(encoding='utf-8')),
           'styles': style_policy,
           'sc021_types': [
               '视线锚点跨界续绘型', '撕纸裂变第二世界型', '越界破框型', '微缩浮岛型',
               '记忆图谱平铺型', '经典悬浮落地型', '正负形咬合型']}
for item in options['tones'] + options['assets']:
    item['image'] = item['image'].replace('../../../images/', 'https://img.handraw-style.com/images/')
(root / 'plugin/content/studio-options.json').write_text(json.dumps(options, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

i18n = source[source.index('const I18N ='):source.index('let currentLang =')]
command = source[source.index('function updatePrompt()'):source.index('function updateSlotUI(')]
adapter = '''
window.HandrawComposerCommand = (draft, resources, options, language = 'zh') => {
  const currentLang = language === 'en' ? 'en' : 'zh';
  const currentMode = draft.mode || 'pure', currentWhitespace = draft.whitespace || 'normal';
  const find = id => id === 'realistic' ? {id, isRealistic:true} : resources.find(item => item.id === id) || null;
  const selectedStyle = find(draft.style), selectedCharStyle = find(draft.character_style), selectedSceneStyle = find(draft.scene_style);
  const selectedLayout = find(draft.layout), selectedColor = find(draft.color);
  const selectedAssets = [...(draft.asset_refs || []).map(id => ({id})), ...(draft.references || []).map(item => ({id:item.name,cat:item.role}))];
  const selectedTones = (draft.tones || []).map(id => options.tones.find(item => item.id === id)).filter(Boolean).map(item => ({...item,name:item.name_zh}));
  const isFusionActive = !!draft.fusion, isToneActive = selectedTones.length > 0, isBatchActive = !!draft.batch, isMixLayoutsActive = !!draft.mix_layouts;
  const inputTheme = {value:draft.theme || ''}, inputAudience = {value:draft.audience || ''}, inputChannel = {value:draft.channel || ''};
  const inputRatio = {value:draft.ratio || ''}, inputMood = {value:draft.mood || ''}, inputShootType = {value:draft.shoot_type || ''};
  const assembledText = {textContent:''};
'''
compiled = '"use strict";\n// Generated from the public Skill. Refresh with ops/refresh_studio.py.\n' + i18n + adapter + command + '\nupdatePrompt();\nreturn assembledText.textContent;\n};\n'
(root / 'plugin/public/composer-core.js').write_text(compiled, encoding='utf-8')
print(f'Imported {len(options["tones"])} tones, {len(options["modes"])} modes and the exact Skill command assembler.')
