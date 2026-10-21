# frozen_string_literal: true

module Jobs
  class HandrawMaintenance < ::Jobs::Scheduled
    every 1.hour

    def execute(args)
      return unless SiteSetting.handraw_enabled
      Handraw::Unlock.active.where(settled_at: nil, held: false).where("settle_at <= ?", Time.current)
        .find_each(&:settle!)
      Handraw::Entry.where(paid_opt_in: true, download_approved: true, status: "published")
        .find_each { |record| Handraw::Economy.reprice!(record) }
    end
  end
end
