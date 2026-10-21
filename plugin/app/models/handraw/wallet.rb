# frozen_string_literal: true

module Handraw
  class Wallet < ActiveRecord::Base
    self.table_name = "handraw_wallets"
    belongs_to :user

    def self.for_user(user_id)
      create_or_find_by!(user_id: user_id)
    end

    def self.change!(user_id, amount, key:, reason:, entry_id: nil, force: false)
      wallet = for_user(user_id)
      wallet.with_lock do
        existing = Ledger.find_by(user_id: user_id, event_key: key)
        return existing if existing
        if amount.negative? && !force && (wallet.frozen || wallet.balance + amount < 0)
          raise Handraw::RuleError, "积分不足或账户已冻结"
        end
        wallet.balance += amount
        wallet.frozen = true if wallet.balance.negative?
        wallet.save!
        Ledger.create!(user_id: user_id, entry_id: entry_id, amount: amount, event_key: key, reason: reason)
      end
    end
  end
end
