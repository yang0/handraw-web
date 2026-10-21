#!/usr/bin/env bash
set -euo pipefail
export PATH="/home/yang0/.local/bin:/home/yang0/.local/share/mise/installs/ruby/3.4.2/bin:/home/yang0/.nvm/versions/node/v24.14.0/bin:$PATH"
export BUNDLE_WITHOUT=none
export BUNDLE_WITH=development:test
export BUNDLE_IGNORE_CONFIG=1
export RAILS_ENV=test
export RAILS_DB=handraw_web_test
export PGUSER=yang0
export DISCOURSE_DB_USERNAME=yang0
export DISCOURSE_REDIS_DB=13
export LOAD_PLUGINS=1
export HANDRAW_PRIVATE_STORAGE=/home/yang0/handraw-data/test-private
export SCHEMA=/home/yang0/handraw-data/test-structure.sql
cd /home/yang0/projectHome/discourse
test "$RAILS_DB" = handraw_web_test
bin/rake db:create
test -f "$SCHEMA" || cp db/structure.sql "$SCHEMA"
# Extension ownership stays with postgres; only the dedicated test schema copy is adjusted.
sed -i '/^COMMENT ON EXTENSION /d' "$SCHEMA"
bin/rake db:schema:load
bin/rake db:migrate
bin/rspec plugins/handraw-community/spec --format documentation
