# frozen_string_literal: true

module Handraw
  class Audit < ActiveRecord::Base
    self.table_name = "handraw_audits"
    belongs_to :user
  end
end
