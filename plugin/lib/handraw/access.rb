# frozen_string_literal: true

module Handraw
  class RuleError < StandardError
  end

  module Access
    def self.verified?(user)
      user && user.active && user.email_confirmed? && !user.staged && !user.suspended? && !user.silenced?
    end

    def self.qualified?(user)
      verified?(user) && user.created_at <= SiteSetting.handraw_qualified_account_days.days.ago
    end

    def self.in_groups?(user, setting)
      ids = setting.to_s.split('|').map(&:to_i)
      ids.present? && user.groups.where(id: ids).exists?
    end

    def self.participant?(user)
      verified?(user) && (user.staff? || SiteSetting.handraw_public_submissions ||
        in_groups?(user, SiteSetting.handraw_pilot_group_ids))
    end

    def self.reviewer?(user)
      verified?(user) && (user.staff? || in_groups?(user, SiteSetting.handraw_reviewer_group_ids))
    end
  end
end
