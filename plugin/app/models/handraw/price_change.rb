# frozen_string_literal: true

module Handraw
  class PriceChange < ActiveRecord::Base
    self.table_name = 'handraw_price_changes'
    belongs_to :entry, class_name: 'Handraw::Entry'
  end
end
