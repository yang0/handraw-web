#!/usr/bin/env bash
# Install a clean, pinned search engine. Run as root on the Handraw host.
set -euo pipefail
umask 077
test "$(id -u)" = 0
VERSION=v1.56.2
HASH=c02e9fc47d425050c27cf77329639f33b5f932e988ef55b6ba4fd2623e93ef64
TASK_DIR=$(mktemp -d /tmp/handraw-search-install.XXXXXX)
STATE=/home/yang0/handraw-data/deployment
mkdir -p "$STATE"
BACKUP="$STATE/before-search-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$BACKUP"
for path in /etc/systemd/system/meilisearch.service /etc/handraw/search.env /etc/handraw/search-engine.env; do
  if test -f "$path"; then cp "$path" "$BACKUP/$(basename "$path")"; fi
done
git -C /home/yang0/projectHome/handraw-web rev-parse HEAD > "$BACKUP/code.txt"
git -C /home/yang0/projectHome/handraw-web diff --binary > "$BACKUP/server.patch"
systemctl cat handraw-v2 > "$BACKUP/website.service"
cp /etc/handraw/handraw-v2.env "$BACKUP/website.env"

curl --fail --location --retry 3 --max-time 240 \
  "https://github.com/meilisearch/meilisearch/releases/download/$VERSION/meilisearch.deb" -o "$TASK_DIR/meilisearch.deb"
printf '%s  %s\n' "$HASH" "$TASK_DIR/meilisearch.deb" | sha256sum --check
(cd "$TASK_DIR" && ar x meilisearch.deb && tar -xf data.tar.*)
BIN=$(find "$TASK_DIR" -type f -path '*/bin/meilisearch' -print -quit)
test -n "$BIN"
"$BIN" --version
if pgrep -x meilisearch >/dev/null; then
  systemctl stop meilisearch
  ! pgrep -x meilisearch >/dev/null
fi
# All deletion targets are explicit Meilisearch-only directories. Reject symlinks.
# User requested removal of old indices/dumps/snapshots, without retaining copies.
python3 - "$BACKUP" <<'PY'
import json,os,shutil,sys
from pathlib import Path
targets=[Path(p) for p in ('/var/lib/handraw-search','/var/lib/meilisearch',
 '/var/opt/meilisearch','/data/meili','/data/meili_data')]
report=[]
for p in targets:
 if p.is_symlink():raise SystemExit('Refusing symlink deletion: '+str(p))
 if p.exists():
  if not p.is_dir():raise SystemExit('Not a search directory: '+str(p))
  report.append({'directory':str(p),'deleted':True});shutil.rmtree(p)
 else:report.append({'directory':str(p),'deleted':False,'reason':'not found'})
Path(sys.argv[1],'old-search-cleanup.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
PY
id handraw-search >/dev/null 2>&1 || useradd --system --home-dir /var/lib/handraw-search --shell /sbin/nologin handraw-search
install -m 755 "$BIN" /usr/local/bin/handraw-meilisearch
install -d -m 700 -o handraw-search -g handraw-search /var/lib/handraw-search
install -d -m 755 /etc/handraw
python3 - <<'PY'
import os,secrets
from pathlib import Path
master,read,write,cursor=[secrets.token_hex(32) for _ in range(4)]
Path('/etc/handraw/search-engine.env').write_text('MEILI_ENV=production\nMEILI_HTTP_ADDR=127.0.0.1:7700\nMEILI_DB_PATH=/var/lib/handraw-search/data.ms\nMEILI_MASTER_KEY='+master+'\nMEILI_NO_ANALYTICS=true\nMEILI_MAX_INDEXING_MEMORY=256MiB\nMEILI_MAX_INDEXING_THREADS=1\n')
Path('/etc/handraw/search.env').write_text('HANDRAW_SEARCH_URL=http://127.0.0.1:7700\nHANDRAW_SEARCH_KEY='+master+'\nHANDRAW_SEARCH_WRITE_KEY='+master+'\nHANDRAW_SEARCH_CURSOR_KEY='+cursor+'\n')
for name in ('search.env','search-engine.env'):os.chmod('/etc/handraw/'+name,0o600)
PY
cat > /etc/systemd/system/handraw-search.service <<'UNIT'
[Unit]
Description=Handraw Meilisearch full-text search
After=network.target
[Service]
User=handraw-search
Group=handraw-search
EnvironmentFile=/etc/handraw/search-engine.env
ExecStart=/usr/local/bin/handraw-meilisearch
WorkingDirectory=/var/lib/handraw-search
Restart=on-failure
RestartSec=5
MemoryHigh=512M
MemoryMax=768M
CPUQuota=100%
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/handraw-search
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now handraw-search
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:7700/health; then break; fi
  sleep 1
done
python3 - <<'PY'
import json,urllib.request
from pathlib import Path
def env(path):return dict(line.split('=',1) for line in Path(path).read_text().splitlines() if '=' in line)
cfg=env('/etc/handraw/search.env');master=cfg['HANDRAW_SEARCH_KEY']
def create(actions):
 req=urllib.request.Request('http://127.0.0.1:7700/keys',method='POST',
  data=json.dumps({'description':'Handraw internal search','actions':actions,'indexes':['handraw_*'],'expiresAt':None}).encode(),
  headers={'Authorization':'Bearer '+master,'Content-Type':'application/json'})
 with urllib.request.urlopen(req) as r:return json.load(r)['key']
cfg['HANDRAW_SEARCH_KEY']=create(['search','indexes.get','stats.get'])
cfg['HANDRAW_SEARCH_WRITE_KEY']=create(['*'])
Path('/etc/handraw/search.env').write_text(''.join(k+'='+v+'\n' for k,v in cfg.items()))
print('Dedicated search and worker keys installed; secret values omitted.')
PY
if getent group yang0 >/dev/null 2>&1; then chown root:yang0 /etc/handraw/search.env && chmod 640 /etc/handraw/search.env; fi
install -d /etc/systemd/system/handraw-v2.service.d
cat > /etc/systemd/system/handraw-v2.service.d/search.conf <<'UNIT'
[Service]
EnvironmentFile=/etc/handraw/search.env
UNIT
cat > /etc/systemd/system/handraw-search-worker.service <<'UNIT'
[Unit]
Description=Handraw durable search indexing worker
After=postgresql.service handraw-search.service
Requires=handraw-search.service
[Service]
User=yang0
Group=yang0
WorkingDirectory=/home/yang0/projectHome/handraw-web
EnvironmentFile=/etc/handraw/handraw-v2.env
EnvironmentFile=/etc/handraw/search.env
ExecStart=/home/yang0/projectHome/handraw-web/.venv/bin/python -m backend.search_worker
Restart=on-failure
RestartSec=5
MemoryHigh=192M
MemoryMax=384M
CPUQuota=50%
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
# Worker starts only after migration and exact-code deployment.
printf '%s\n' "$BACKUP" > "$STATE/search-install-backup"
systemctl is-active handraw-search
