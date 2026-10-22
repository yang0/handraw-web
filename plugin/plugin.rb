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
require_relative 'lib/handraw/navigation'
require_relative 'lib/handraw/image_service'
require_relative 'lib/handraw/catalog'
require_relative 'lib/handraw/publishing'
require_relative 'lib/handraw/creation'
require_relative 'lib/handraw/private_media'

register_html_builder('server:before-head-close') do |controller|
  nonce = ContentSecurityPolicy.nonce_placeholder(controller.response.headers, request_env: controller.request.env)
  Handraw::Navigation.stylesheet(nonce: nonce)
end
register_html_builder('server:after-body-open') { |_controller| Handraw::Navigation.render(active: 'community', surface: 'forum') }

after_initialize do
  Rails.application.config.filter_parameters += %i[content prompt creation definition_zh definition_en]
  Discourse::Application.routes.append { mount ::Handraw::Engine, at: '/studio' }
  require_relative 'app/jobs/scheduled/handraw_maintenance'
end
