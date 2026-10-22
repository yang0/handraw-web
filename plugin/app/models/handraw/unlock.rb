# frozen_string_literal: true

module Handraw
  class Unlock < ActiveRecord::Base
    self.table_name = 'handraw_unlocks'
    belongs_to :user
    belongs_to :entry, class_name: 'Handraw::Entry'

    scope :active, -> { where(refunded_at: nil) }

    def settle!
      with_lock do
        return if settled_at || refunded_at || held || settle_at > Time.current
        return if Wallet.for_user(author_id).locked

        if author_amount.positive?
          Wallet.change!(
            author_id,
            author_amount,
            key: "sale:#{id}",
            reason: '内容解锁收益',
            entry_id: entry_id
          )
        end
        update!(settled_at: Time.current)
      end
    end

    def refund!(reviewer, reason)
      raise Handraw::RuleError, '不能审核自己的交易' if [user_id, author_id].include?(reviewer.id)

      with_lock do
        return if refunded_at

        [user_id, author_id].sort.each { |account_id| Wallet.for_user(account_id).lock! }
        Wallet.change!(user_id, amount, key: "refund:#{id}", reason: reason, entry_id: entry_id)
        if settled_at && author_amount.positive?
          Wallet.change!(
            author_id,
            -author_amount,
            key: "clawback:#{id}",
            reason: reason,
            entry_id: entry_id,
            force: true
          )
        end
        update!(refunded_at: Time.current, held: true)
        Event.where(entry_id: entry_id, user_id: user_id, kind: %w[useful not_useful]).update_all(qualified: false)
        Audit.create!(user_id: reviewer.id, entry_id: entry_id, action: 'refund', reason: reason,
                      details: { unlock_id: id })
      end
    end
  end
end
