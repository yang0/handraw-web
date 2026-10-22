# frozen_string_literal: true

module Handraw
  class AssetLink < ActiveRecord::Base
    self.table_name = 'handraw_asset_links'
    belongs_to :entry, class_name: 'Handraw::Entry'
  end
end
