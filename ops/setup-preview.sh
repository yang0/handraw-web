#!/usr/bin/env bash
set -euo pipefail
export PATH="/home/yang0/.local/bin:/home/yang0/.local/share/mise/installs/ruby/3.4.2/bin:/home/yang0/.nvm/versions/node/v24.14.0/bin:$PATH"
export RAILS_ENV=development
export DISCOURSE_DEV_DB=handraw_web_preview
export PGUSER=yang0
export DISCOURSE_DB_USERNAME=yang0
export DISCOURSE_REDIS_DB=12
export DISCOURSE_HOSTNAME=localhost
export SKIP_TEST_DATABASE=1
export BUNDLE_IGNORE_CONFIG=1
export HANDRAW_PRIVATE_STORAGE=/home/yang0/handraw-data/preview-private
export SCHEMA=/home/yang0/handraw-data/preview-structure.sql
cd /home/yang0/projectHome/discourse
if ! psql handraw_web_preview -Atc "SELECT to_regclass('public.users')" | grep -q users; then
  sudo -n -u postgres psql handraw_web_preview -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS hstore; CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS pg_trgm;'
  cp db/structure.sql "$SCHEMA"
  sed -i '/^COMMENT ON EXTENSION /d' "$SCHEMA"
  psql --set ON_ERROR_STOP=1 --single-transaction --file "$SCHEMA" handraw_web_preview > /dev/null
fi
bin/rake db:migrate db:seed_fu
bin/rails runner /home/yang0/projectHome/handraw-web/ops/setup-preview.rb
