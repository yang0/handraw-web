# frozen_string_literal: true

require 'rails_helper'

RSpec.describe Handraw::Economy do
  fab!(:author) { Fabricate(:user, active: true, created_at: 14.days.ago) }
  fab!(:topic) { Fabricate(:topic, user: author) }
  fab!(:resource) do
    Handraw::Entry.create!(user: author, topic: topic, public_id: SecureRandom.uuid,
                           kind: 'style', title: '可复用的水彩风格', summary: '适合不同主题的水彩纸面与自然晕染效果。',
                           license: '个人创作与商业输出均可使用。', content_digest: SecureRandom.hex(32),
                           paid_opt_in: true, download_approved: true, created_at: 8.days.ago)
  end

  before { SiteSetting.handraw_enabled = true }

  describe '.reprice!' do
    it 'uses configurable initial prices and feedback thresholds' do
      SiteSetting.handraw_price_initial = 15
      SiteSetting.handraw_price_min_ratings = 1
      SiteSetting.handraw_price_step = 3
      fresh = resource.dup
      fresh.public_id = SecureRandom.uuid
      fresh.content_digest = SecureRandom.hex(32)
      fresh.save!
      expect(fresh.price).to eq(15)
      user = Fabricate(:user, active: true, created_at: 14.days.ago)
      fresh.events.create!(user: user, kind: 'not_useful', qualified: true, day: Date.current)
      described_class.reprice!(fresh)
      expect(fresh.reload.price).to eq(12)
    end

    it 'keeps the price stable with too little evidence and observes the weekly cooldown' do
      described_class.reprice!(resource)
      expect(resource.reload.price).to eq(10)
      resource.update!(price: 15)
      described_class.reprice!(resource)
      expect(resource.reload.price).to eq(15)
    end

    it 'lowers the price for enough poor usage feedback and stops at the lower bound' do
      5.times do
        user = Fabricate(:user, active: true, created_at: 14.days.ago)
        resource.events.create!(user: user, kind: 'not_useful', qualified: true, day: Date.current)
      end
      described_class.reprice!(resource)
      expect(resource.reload.price).to eq(5)
      resource.update!(last_priced_at: 8.days.ago)
      described_class.reprice!(resource)
      expect(resource.reload.price).to eq(5)
    end
  end

  describe '.editorial_award!' do
    it 'tops up to the greater award rather than double paying' do
      resource.with_lock do
        described_class.editorial_award!(resource, 20)
        described_class.editorial_award!(resource, 30)
        described_class.editorial_award!(resource, 20)
      end
      expect(Handraw::Wallet.for_user(author.id).balance).to eq(30)
    end
  end
end
