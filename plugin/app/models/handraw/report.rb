# frozen_string_literal: true

module Handraw
  class Report < ActiveRecord::Base
    self.table_name = "handraw_reports"
    belongs_to :user
    belongs_to :entry, class_name: "Handraw::Entry"
  end
end
