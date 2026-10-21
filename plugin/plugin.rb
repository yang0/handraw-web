# frozen_string_literal: true

# name: handraw-community
# about: Handraw portal, community resources, credits and private library sync
# version: 0.1.0
# authors: yang0
# url: https://github.com/yang0/handraw-web
# required_version: 3.4.0

enabled_site_setting :handraw_enabled

module ::Handraw
  PLUGIN_NAME = 'handraw-community'
end

require_relative 'lib/handraw/engine'
require_relative 'lib/handraw/access'
require_relative 'lib/handraw/economy'
require_relative 'lib/handraw/feed'
require_relative 'lib/handraw/bundle_store'

after_initialize do
  Discourse::Application.routes.append { mount ::Handraw::Engine, at: '/studio' }
  require_relative 'app/jobs/scheduled/handraw_maintenance'
end
