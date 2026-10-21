# frozen_string_literal: true

module Handraw
  class Engine < ::Rails::Engine
    engine_name Handraw::PLUGIN_NAME
    isolate_namespace Handraw
  end
end
