#!/usr/bin/env bash
set -euo pipefail
umask 077
WEB=/home/yang0/projectHome/handraw-web
CORE=/home/yang0/projectHome/discourse
STATE=/home/yang0/handraw-data/deployment
export PATH="/home/yang0/.local/bin:/home/yang0/.local/share/mise/installs/ruby/3.4.2/bin:/home/yang0/.nvm/versions/node/v24.14.0/bin:$PATH"
mkdir -p "$STATE" "$WEB/.local/releases"
exec 9>"$STATE/deploy.lock"
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
cd "$WEB"
command_name=${1:-status}

fingerprint_core() {
  { git -C "$CORE" diff --binary; git -C "$CORE" ls-files --others --exclude-standard; } | sha256sum | cut -d' ' -f1
}

activate() {
  local release=$1
  test -f "$WEB/.local/releases/$release/plugin/plugin.rb"
  ln -s "$WEB/.local/releases/$release/plugin" "$CORE/plugins/handraw-community.next"
  mv -Tf "$CORE/plugins/handraw-community.next" "$CORE/plugins/handraw-community"
  sudo -n supervisorctl restart discourse:discourse-web discourse:discourse-sidekiq
}

healthy() {
  for attempt in $(seq 1 30); do
    if curl --fail --silent --max-time 10 -H 'Host: handraw-style.com' http://127.0.0.1:3000/studio/api/boot > "$STATE/health.json" &&
       curl --fail --silent --max-time 10 -H 'Host: handraw-style.com' http://127.0.0.1:3000/latest.json > /dev/null; then return 0; fi
    sleep 2
  done
  return 1
}

case "$command_name" in
status)
  printf 'repository '; git rev-parse HEAD
  printf 'production '; cat "$STATE/current" 2>/dev/null || true
  printf 'previous '; cat "$STATE/previous" 2>/dev/null || true
  git status --short
  sudo -n supervisorctl status discourse:discourse-web discourse:discourse-sidekiq
  ;;
capture-baseline)
  fingerprint_core > "$STATE/core-baseline"
  echo 'Existing core modifications recorded; future drift will stop deployment.'
  ;;
deploy)
  commit=${2:?Specify a full commit SHA}
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit'; exit 1; }
  test -z "$(git status --porcelain)" || { echo 'Dirty server checkout; refusing overwrite'; exit 1; }
  test -f "$STATE/core-baseline"
  test "$(fingerprint_core)" = "$(cat "$STATE/core-baseline")" || { echo 'Discourse changes differ from the preserved baseline'; exit 1; }
  git fetch origin main
  git merge-base --is-ancestor "$commit" origin/main
  git merge --ff-only origin/main
  release="$WEB/.local/releases/$commit"
  mkdir -p "$release"
  git archive "$commit" plugin | tar -x -C "$release"
  find "$release/plugin" -name '*.rb' -print0 | xargs -0 -n1 ruby -c > "$STATE/syntax-check.log"
  backup="$STATE/database-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
  sudo -n -u postgres pg_dump discourse | gzip > "$backup"
  gzip -t "$backup"
  previous=$(cat "$STATE/current" 2>/dev/null || true)
  ln -s "$release/plugin" "$CORE/plugins/handraw-community.next"
  mv -Tf "$CORE/plugins/handraw-community.next" "$CORE/plugins/handraw-community"
  if ! (cd "$CORE" && RAILS_ENV=production SCHEMA="$STATE/production-structure.sql" bin/rake db:migrate); then
    if test -n "$previous"; then activate "$previous"; fi
    echo 'Migration failed. Database backup preserved; no destructive down migration was run.' >&2
    exit 1
  fi
  (cd "$CORE" && RAILS_ENV=production bin/rails runner "$WEB/ops/configure-production.rb")
  printf '%s\n' "$commit" > "$STATE/candidate"
  sudo -n supervisorctl restart discourse:discourse-web discourse:discourse-sidekiq
  if ! healthy; then
    if test -n "$previous"; then activate "$previous"; else echo 'Initial deployment needs operator inspection; feature remains disabled unless explicitly enabled.' >&2; fi
    exit 1
  fi
  test -z "$previous" || printf '%s\n' "$previous" > "$STATE/previous"
  printf '%s\n' "$commit" > "$STATE/current"
  fingerprint_core > "$STATE/core-baseline"
  echo "Deployed $commit"
  ;;
rollback)
  previous=$(cat "$STATE/previous")
  current=$(cat "$STATE/current")
  [[ "$previous" =~ ^[0-9a-f]{40}$ ]]
  test -z "$(git status --porcelain)" || { echo 'Dirty checkout; refusing rollback'; exit 1; }
  activate "$previous"
  if ! healthy; then activate "$current"; echo 'Rollback health check failed; restored current release'; exit 1; fi
  printf '%s\n' "$previous" > "$STATE/current"
  printf '%s\n' "$current" > "$STATE/previous"
  fingerprint_core > "$STATE/core-baseline"
  echo "Rolled back code to $previous; database retained"
  ;;
*) echo 'Usage: server-deploy.sh status|capture-baseline|deploy SHA|rollback' >&2; exit 2 ;;
esac
