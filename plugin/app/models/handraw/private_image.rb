# frozen_string_literal: true

module Handraw
  class PrivateImage < ActiveRecord::Base
    self.table_name = 'handraw_private_images'
    belongs_to :entry, class_name: 'Handraw::Entry', optional: true
  end
end
