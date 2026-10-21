"""Connect the existing local image service without printing or committing its key."""
import json
import os
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

source = Path('/home/yang0/projectHome/chatgpt2api/config.json')
target = Path('/home/yang0/handraw-data/image-service.json')
assert target.resolve().parent == Path('/home/yang0/handraw-data').resolve()
data = json.loads(source.read_text())
key = data.get('auth-key') or data.get('auth_key') or data.get('config', {}).get('auth_key')
if not isinstance(key, str) or not key.strip():
    raise SystemExit('The existing service does not have an auth_key in its configuration; no changes made.')
request = urllib.request.Request('http://127.0.0.1:8000/v1/models', headers={'Authorization': f'Bearer {key}'})
with urllib.request.urlopen(request, timeout=10) as response:
    models = json.load(response)
if not isinstance(models.get('data'), list):
    raise SystemExit('Model endpoint verification failed; no changes made.')
target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
if target.exists():
    backup = target.with_name('image-service-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    shutil.copyfile(target, backup)
    backup.chmod(0o600)
candidate = target.with_suffix('.next')
descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, 'w') as output:
    json.dump({'url': 'http://127.0.0.1:8000', 'key': key}, output)
candidate.chmod(0o600)
candidate.replace(target)
print('Existing image service verified and connected; private configuration stored outside Git. No image was generated.')
