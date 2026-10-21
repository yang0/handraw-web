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
      expect(response.body).to include('/studio/assets/image-loader.js')
      get '/studio', params: { view: 'experience' }
      expect(response.body).to include('id="hero" hidden', 'data-site-section="community" aria-current="page"')
      get '/latest.json'
      expect(response.status).to eq(200)
    end
  end

  describe '#asset' do
    it 'serves the public portal script to browser script tags' do
      get '/studio/assets/portal.js'
      expect(response.status).to eq(200)
      expect(response.media_type).to eq('text/javascript')
      get '/studio/assets/image-loader.js'
      expect(response.status).to eq(200)
      expect(response.media_type).to eq('text/javascript')
    end
  end

  describe 'online generation access' do
    it 'requires login and preserves ownership through submit and history routes' do
      get '/studio/api/generations.json'
      expect(response.status).to eq(403)
      sign_in(buyer)
      Handraw::ImageService.stubs(:enabled?).returns(true)
      Handraw::ImageService.stubs(:request).returns('status' => 'queued')
      post '/studio/api/generations.json', params: {
        client_id: SecureRandom.uuid, prompt: '一只在窗边晒太阳的小猫', title: '窗边小猫', ratio: '1:1'
      }
      expect(response.status).to eq(200)
      id = response.parsed_body['id']
      get '/studio/api/generations.json'
      expect(response.parsed_body['tasks'].map { |task| task['id'] }).to include(id)
      sign_in(author)
      get '/studio/api/generations.json'
      expect(response.parsed_body['tasks']).to eq([])
      get "/studio/api/generations/#{id}/image", params: { index: '0' }
      expect(response.status).to eq(404)
    end

    it 'does not grant generation rights to a signed-in account outside the pilot' do
      SiteSetting.handraw_public_submissions = false
      sign_in(buyer)
      Handraw::ImageService.expects(:submit).never
      post '/studio/api/generations.json', params: { client_id: SecureRandom.uuid, prompt: '一只猫咪', ratio: '1:1' }
      expect(response.status).to eq(403)
    end
  end

  describe '#impressions' do
    it 'accepts a visible batch once per day and ignores self impressions' do
      sign_in(buyer)
      samples = [{ id: resource.public_id, visible_ms: 2000, visible_ratio: 0.5 }]
      2.times do
        post '/studio/api/impressions.json', params: { entries: samples }
        expect(response.status).to eq(204)
      end
      expect(resource.events.where(user_id: buyer.id, kind: 'impression', qualified: true).count).to eq(1)
      sign_in(author)
      post '/studio/api/impressions.json', params: { entries: samples }
      expect(resource.events.where(user_id: author.id).count).to eq(0)
    end
  end

  describe 'forum navigation' do
    it 'keeps the site navigation on the forum and topic pages' do
      LetterAvatar.stubs(:version).returns('navigation-test')
      headers = { 'User-Agent' => 'Mozilla/5.0 Chrome/130.0 Safari/537.36' }
      get '/latest', headers: headers
      expect(response.status).to eq(200)
      expect(response.body).to include('data-surface="forum"', 'data-site-section="community" aria-current="page"')
      Fabricate(:post, topic: topic, user: author)
      get topic.relative_url, headers: headers
      expect(response.status).to eq(200)
      expect(response.body).to include('data-surface="forum"')
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
    it 'delivers the actual private attachment only after unlocking and forbids public caching' do
      FileUtils.mkdir_p(Handraw::BundleStore.root)
      Tempfile.create(['handraw-private', '.zip'], Handraw::BundleStore.root) do |file|
        file.write('private resource attachment')
        file.flush
        resource.update!(bundle_key: File.basename(file.path), bundle_sha256: Digest::SHA256.file(file.path).hexdigest)
        Handraw::Wallet.change!(buyer.id, 10, key: 'download-seed', reason: '测试积分')
        Handraw::Economy.unlock!(resource, buyer, 10, 1)
        sign_in(buyer)
        get "/studio/api/entries/#{resource.public_id}/download"
        expect(response.status).to eq(200)
        expect(response.body).to eq('private resource attachment')
        expect(response.headers['Cache-Control']).to include('private', 'no-store')
      end
    end

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
    it 'accepts a simple submission without asking the author to choose a board or license' do
      sign_in(reviewer)
      post '/studio/api/entries.json', params: { entry: { kind: 'experience', title: '一个清楚的创作经验标题',
                                                         summary: '先选择目标，再记录步骤，最后贴上结果，帮助其他创作者复用方法。' } }
      expect(response.status).to eq(201)
      expect(Handraw::Entry.find_by!(public_id: response.parsed_body.fetch('id')).license).to include('联系原作者')
    end

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
