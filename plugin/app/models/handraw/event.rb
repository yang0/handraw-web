# frozen_string_literal: true

module Handraw
  class Event < ActiveRecord::Base
    self.table_name = "handraw_events"
    belongs_to :user
    belongs_to :entry, class_name: "Handraw::Entry"
  end
end
