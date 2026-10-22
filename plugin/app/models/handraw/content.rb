# frozen_string_literal: true

module Handraw
  class Content < ActiveRecord::Base
    self.table_name = 'handraw_contents'
    belongs_to :entry, class_name: 'Handraw::Entry'
  end






end
