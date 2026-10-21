# frozen_string_literal: true

module Handraw
  class Collection < ActiveRecord::Base
    self.table_name = 'handraw_collections'
    belongs_to :user
    belongs_to :entry, class_name: 'Handraw::Entry'
  end
end
