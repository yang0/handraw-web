#!/usr/bin/env bash
# Reviewed existing production launcher; reference only.
export PATH="/home/yang0/.nvm/versions/node/v24.14.0/bin:/home/yang0/.local/share/mise/installs/ruby/3.4.2/bin:/usr/local/bin:/usr/bin:/bin"
export RAILS_ENV=production
exec bundle exec sidekiq -q critical,8 -q default,4 -q low,2 -q ultra_low,1
