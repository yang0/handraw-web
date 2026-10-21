#!/usr/bin/env bash
# Reviewed existing production launcher; reference only, not overwritten by deploys.
export PATH="/home/yang0/.nvm/versions/node/v24.14.0/bin:/home/yang0/.local/share/mise/installs/ruby/3.4.2/bin:/usr/local/bin:/usr/bin:/bin"
export RAILS_ENV=production
export UNICORN_WORKERS=2
export UNICORN_PORT=3000
exec bundle exec pitchfork -c config/pitchfork.conf.rb
