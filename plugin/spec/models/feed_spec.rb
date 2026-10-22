# frozen_string_literal: true

require 'rails_helper'

RSpec.describe Handraw::Feed do
  fab!(:author) { Fabricate(:user, active: true) }
  fab!(:another_author) { Fabricate(:user, active: true) }

  describe '.call' do
    it 'gives one initial exploration candidate per author and retains old low-exposure work' do
      entries = [author, author, another_author].each_with_index.map do |user, index|
        topic = Fabricate(:topic, user: user)
        Handraw::Entry.create!(user: user, topic: topic, public_id: SecureRandom.uuid, kind: 'work',
                               cover_url: 'https://img.handraw-style.com/images/individual/FA/FA-001.webp',
                               title: "作品 #{index} 的初次曝光", summary: '新的创作应该得到真实用户的初次反馈机会。',
                               license: '允许浏览欣赏，转载请先联系作者。', content_digest: SecureRandom.hex(32), created_at: (20 - index).days.ago)
      end
      results = described_class.call(kind: 'work')
      expect(results.map(&:id)).to contain_exactly(entries[0].id, entries[2].id)
      expect(described_class.call(kind: 'work', search: '真实用户').map(&:id)).to contain_exactly(*entries.map(&:id))
      expect(described_class.call(kind: 'work', sort: 'latest').map(&:id)).to eq(entries.reverse.map(&:id))
    end

    it 'keeps forum articles and text-only entries out of work lists without removing their topics' do
      entries = 3.times.map do |index|
        user = Fabricate(:user)
        Handraw::Entry.create!(user: user, topic: Fabricate(:topic, user: user), public_id: SecureRandom.uuid,
                              kind: 'work', title: "内容边界检查 #{index} 的分享", summary: '作品列表仅展示用户主动分享的真实成图。',
                              license: '允许浏览欣赏，转载请联系作者。', content_digest: SecureRandom.hex(32),
                              cover_url: index == 2 ? '' : 'https://img.handraw-style.com/images/individual/FA/FA-001.webp',
                              metadata: index == 1 ? { 'imported_from_forum' => true } : {})
      end
      [nil, 'latest'].each do |sort|
        expect(described_class.call(kind: 'work', sort: sort).map(&:id)).to eq([entries.first.id])
      end
      expect(described_class.call(kind: 'work', search: '内容边界').map(&:id)).to eq([entries.first.id])
      expect(described_class.call(sort: 'latest').map(&:id)).to eq([entries.first.id])
      expect(Topic.where(id: entries.map(&:topic_id)).count).to eq(3)
    end
  end
end
