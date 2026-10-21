# frozen_string_literal: true

module Handraw
  module Economy
    def self.welcome!(user, accepted)
      raise RuleError, '请验证账号并确认完成新人任务' unless Access.participant?(user) && accepted

      Wallet.change!(user.id, SiteSetting.handraw_welcome_credits, key: 'welcome', reason: '完成新人任务')
    end

    def self.unlock!(entry, user, expected_price, expected_revision)
      raise RuleError, '请先登录获准参与的账号' unless Access.participant?(user)

      entry.with_lock do
        existing = entry.unlocks.find_by(user_id: user.id)
        raise RuleError, '此资源已退款，请先联系版主处理' if existing&.refunded_at
        return existing if existing
        raise RuleError, '资源暂未开放下载' unless entry.status == 'published' && entry.download_approved && entry.bundled?

        amount = entry.paid_opt_in ? entry.price : 0
        raise RuleError, '价格已变化，请刷新后重新确认' if amount != expected_price || entry.price_revision != expected_revision
        return nil if entry.user_id == user.id

        Wallet.change!(user.id, -amount, key: "unlock:#{entry.id}", reason: '解锁资源', entry_id: entry.id)
        entry.unlocks.create!(
          user_id: user.id,
          author_id: entry.user_id,
          amount: amount,
          author_amount: amount * 80 / 100,
          settle_at: 7.days.from_now
        )
      end
    end

    def self.contribution!(entry)
      entry.with_lock do
        users = entry.qualified_events.where(kind: 'useful').distinct.pluck(:user_id)
        return if users.size < 3

        wallet = Wallet.for_user(entry.user_id)
        wallet.with_lock do
          return if Ledger.exists?(user_id: entry.user_id, event_key: "contribution:#{entry.id}")

          awarded_today = Ledger.where(user_id: entry.user_id, created_at: Time.current.beginning_of_day..)
                                .where("event_key LIKE 'contribution:%'").count
          return if awarded_today >= SiteSetting.handraw_daily_contribution_limit

          Wallet.change!(entry.user_id, SiteSetting.handraw_contribution_credits,
                         key: "contribution:#{entry.id}", reason: '原创贡献获得有效使用认可', entry_id: entry.id)
        end
      end
    end

    def self.editorial_award!(entry, target)
      granted = Ledger.where(user_id: entry.user_id, entry_id: entry.id)
                      .where("event_key LIKE 'editorial:%'").sum(:amount)
      return if target <= granted

      Wallet.change!(entry.user_id, target - granted,
                     key: "editorial:#{entry.id}:#{target}", reason: '精选与资源复用奖励', entry_id: entry.id)
    end

    def self.reprice!(entry, now = Time.current)
      entry.with_lock do
        return unless entry.paid_opt_in && entry.download_approved && entry.status == 'published'
        return if (entry.last_priced_at || entry.created_at) > now - 7.days

        window = (now - 7.days)..now
        sales = entry.unlocks.where(created_at: window)
        valid_sales = sales.active.joins(:user).where(users: { active: true, staged: false })
                           .where('users.created_at <= ?', now - 7.days)
        ratings = entry.qualified_events.where(kind: %w[useful not_useful], created_at: window)
        votes = ratings.distinct.count(:user_id)
        useful = ratings.where(kind: 'useful').distinct.count(:user_id)
        visitors = entry.qualified_events.where(kind: 'detail', created_at: window).distinct.count(:user_id)
        complaints = Report.where(entry_id: entry.id, status: 'confirmed', created_at: window).distinct.count(:user_id)
        old = entry.price
        reason = '样本不足或表现稳定，价格不变'
        if (visitors >= 50 && valid_sales.count.zero?) || (votes >= 5 && useful.to_f / votes < 0.6)
          entry.price = [old - 5, 5].max
          reason = '有效访问未转化或使用反馈较弱，下调一档'
        elsif valid_sales.count >= 10 && votes >= 5 && useful.to_f / votes >= 0.8 &&
              complaints.to_f / [sales.count, 1].max <= 0.05
          entry.price = [old + 5, 30].min
          reason = '有效获取与使用反馈达到标准，上调一档'
        end
        entry.last_priced_at = now
        entry.price_reason = reason
        entry.price_revision += 1 if entry.price != old
        entry.save!
        PriceChange.create!(entry_id: entry.id, old_price: old, new_price: entry.price, reason: reason)
      end
    end
  end
end
