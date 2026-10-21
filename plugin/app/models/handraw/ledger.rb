# frozen_string_literal: true

module Handraw
  class Ledger < ActiveRecord::Base
    self.table_name = 'handraw_ledgers'
    belongs_to :user
  end
end
