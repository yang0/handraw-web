# frozen_string_literal: true

require 'rails_helper'

RSpec.describe Handraw::PortalController do
  fab!(:author) { Fabricate(:user, active: true, created_at: 14.days.ago) }
  fab!(:buyer) { Fabricate(:user, active: true, created_at: 14.days.ago) }
  fab!(:reviewer) { Fabricate(:admin, active: true) }
  fab!(:topic) { Fabricate(:topic, user: author) }
  fab!(:resource) do
    Handraw::Entry.create!(user: author, topic: topic, public_id: SecureRandom.uuid,
                           kind: 'style', title: '可复用的水彩风格', summary: '用于不同主题的温润水彩与细腻纸张肌理。',
                           license: '允许个人及商业创作，禁止原包转售。', content_digest: SecureRandom.hex(32),
                           bundle_key: 'test.zip', bundle_sha256: 'a' * 64, featured: true,
                           download_approved: true, paid_opt_in: true)
  end

  before do
    SiteSetting.handraw_enabled = true
    SiteSetting.handraw_public_submissions = true
  end

  describe '#index' do
    it 'serves the independent portal and keeps existing discussion routes accessible' do
      get '/studio'
      expect(response.status).to eq(200)
      expect(response.body).to include('手绘风')
      get '/latest.json'
      expect(response.status).to eq(200)
    end
  end

  describe '#asset' do
    it 'serves the public portal script to browser script tags' do
      get '/studio/assets/portal.js'
      expect(response.status).to eq(200)
      expect(response.media_type).to eq('text/javascript')
    end
  end

  describe '#unlock' do
    before { sign_in(buyer) }

    it 'charges once across retries and preserves the entitlement after uncollecting' do
      Handraw::Wallet.change!(buyer.id, 10, key: 'test-grant', reason: '测试积分')
      2.times do
        post "/studio/api/entries/#{resource.public_id}/unlock.json", params: { price: 10, price_revision: 1 }
        expect(response.status).to eq(200)
      end
      delete "/studio/api/entries/#{resource.public_id}/collection.json"
      expect(response.status).to eq(204)
      expect(Handraw::Wallet.for_user(buyer.id).balance).to eq(0)
      expect(Handraw::Unlock.where(user_id: buyer.id, entry_id: resource.id).count).to eq(1)
      expect(resource.accessible_to?(buyer)).to eq(true)
    end

    it 'rejects insufficient balance without granting access or creating a sale' do
      post "/studio/api/entries/#{resource.public_id}/unlock.json", params: { price: 10, price_revision: 1 }
      expect(response.status).to eq(422)
      expect(resource.unlocks.count).to eq(0)
    end

    it 'requires a new confirmation after a price revision' do
      Handraw::Wallet.change!(buyer.id, 20, key: 'test-grant', reason: '测试积分')
      resource.update!(price: 15, price_revision: 2)
      post "/studio/api/entries/#{resource.public_id}/unlock.json", params: { price: 10, price_revision: 1 }
      expect(response.status).to eq(422)
      expect(Handraw::Wallet.for_user(buyer.id).balance).to eq(20)
    end
  end

  describe '#download' do
    it 'denies the protected attachment to a signed-in user without an entitlement' do
      sign_in(buyer)
      get "/studio/api/entries/#{resource.public_id}/download"
      expect(response.status).to eq(403)
    end

    it 'requires authentication for protected downloads' do
      get "/studio/api/entries/#{resource.public_id}/download"
      expect(response.status).to eq(404)
      expect(response.headers['Content-Disposition']).to be_nil
    end
  end

  describe '#review' do
    it 'rejects ordinary users and self review even for staff' do
      sign_in(buyer)
      post "/studio/api/entries/#{resource.public_id}/review.json",
           params: { action_name: 'feature', reason: '该内容具有复用价值' }
      expect(response.status).to eq(403)
      author.update!(admin: true)
      sign_in(author)
      post "/studio/api/entries/#{resource.public_id}/review.json",
           params: { action_name: 'feature', reason: '自己申请精选审核' }
      expect(response.status).to eq(422)
    end
  end

  describe '#welcome' do
    it 'issues the welcome reward exactly once' do
      sign_in(buyer)
      2.times do
        post '/studio/api/welcome.json', params: { accepted: true }
        expect(response.status).to eq(200)
      end
      expect(Handraw::Wallet.for_user(buyer.id).balance).to eq(10)
    end
  end

  describe '#create' do
    it 'publishes a public contribution with its discussion and rejects duplicate content' do
      sign_in(reviewer)
      payload = { kind: 'experience', title: '水彩风格的三步创作过程',
                  summary: '先明确使用场景，再选择视觉语言，最后用不同主题验证复用效果。',
                  license: '允许学习参考，转载请联系原作者。', category_id: topic.category_id }
      post '/studio/api/entries.json', params: { entry: payload }
      expect(response.status).to eq(201)
      created = Handraw::Entry.find_by!(public_id: response.parsed_body.fetch('id'))
      expect(created.topic.user_id).to eq(reviewer.id)
      post '/studio/api/entries.json', params: { entry: payload }
      expect(response.status).to eq(422)
    end
  end

  describe '#refund' do
    it 'returns buyer credits, cancels pending author income, and is idempotent' do
      Handraw::Wallet.change!(buyer.id, 10, key: 'test-grant', reason: '测试积分')
      sale = Handraw::Economy.unlock!(resource, buyer, 10, 1)
      sign_in(reviewer)
      2.times do
        post "/studio/api/unlocks/#{sale.id}/refund.json", params: { reason: '资源损坏，已确认退回积分' }
        expect(response.status).to eq(204)
      end
      sale.reload.settle!
      expect(Handraw::Wallet.for_user(buyer.id).balance).to eq(10)
      expect(Handraw::Wallet.for_user(author.id).balance).to eq(0)
      expect(resource.accessible_to?(buyer)).to eq(false)
    end
  end
end
