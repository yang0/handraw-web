#!/usr/bin/env bash
set -euo pipefail
export PATH="/home/yang0/.local/bin:/home/yang0/.local/share/mise/installs/ruby/3.4.2/bin:/home/yang0/.nvm/versions/node/v24.14.0/bin:$PATH"
export RAILS_ENV=development
export DISCOURSE_DEV_DB=handraw_web_preview
export PGUSER=yang0
export DISCOURSE_DB_USERNAME=yang0
export DISCOURSE_REDIS_DB=12
export DISCOURSE_HOSTNAME=localhost
export HANDRAW_PRIVATE_STORAGE=/home/yang0/handraw-data/preview-private
export BUNDLE_WITHOUT=none
export BUNDLE_WITH=development:test
export BUNDLE_IGNORE_CONFIG=1
export PORT=3010
cd /home/yang0/projectHome/discourse
exec bundle exec puma -b tcp://127.0.0.1:3010 -t 1:2 -w 0
