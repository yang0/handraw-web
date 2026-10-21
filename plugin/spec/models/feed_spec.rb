# frozen_string_literal: true

require "rails_helper"

RSpec.describe Handraw::Feed do
  fab!(:author) { Fabricate(:user, active: true) }
  fab!(:another_author) { Fabricate(:user, active: true) }

  describe ".call" do
    it "gives one initial exploration candidate per author and retains old low-exposure work" do
      entries = [author, author, another_author].each_with_index.map do |user, index|
        topic = Fabricate(:topic, user: user)
        Handraw::Entry.create!(user: user, topic: topic, public_id: SecureRandom.uuid, kind: "work",
          title: "作品 #{index} 的初次曝光", summary: "新的创作应该得到真实用户的初次反馈机会。",
          license: "允许浏览欣赏，转载请先联系作者。", content_digest: SecureRandom.hex(32), created_at: (20 - index).days.ago)
      end
      results = described_class.call
      expect(results.map(&:id)).to contain_exactly(entries[0].id, entries[2].id)
    end
  end
end
