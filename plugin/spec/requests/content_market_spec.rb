# frozen_string_literal: true

require 'rails_helper'

RSpec.describe 'Handraw content market' do
  fab!(:author) { Fabricate(:user, active: true, created_at: 20.days.ago) }
  fab!(:buyer) { Fabricate(:user, active: true, created_at: 20.days.ago) }
  fab!(:reviewer) { Fabricate(:admin, active: true) }
  let(:secret) { "PRIVATE-DEFINITION-#{SecureRandom.hex(12)}" }

  before do
    [author, buyer, reviewer].each { |user| user.activate unless user.email_confirmed? }
    SiteSetting.handraw_enabled = true
    SiteSetting.handraw_public_submissions = true
    SiteSetting.create_topic_allowed_groups = Group::AUTO_GROUPS[:everyone].to_s
  end

  def publish(kind = 'work', extra = {})
    payload = { kind: kind, title: "画风社区的完整创作记录 #{kind} #{SecureRandom.hex(4)}", summary: '这是公开的预览说明，完整方法与定义独立保护。',
                cover_url: 'https://img.handraw-style.com/images/individual/FA/FA-001.webp',
                price: 10, paid_opt_in: true,
                content: { prompt: secret, body: secret, definition_zh: secret, parameters: { model: 'test' } } }.merge(extra)
    Handraw::Publishing.create!(author, payload, Guardian.new(author))
  end

  def grant(user = buyer, amount = 100)
    Handraw::Wallet.change!(user.id, amount, key: SecureRandom.uuid, reason: '隔离测试积分')
  end

  it 'allows forum experience scripts through the native Discourse nonce policy' do
    # Avatar rendering is unrelated to this HTML/CSP check and requires an external ImageMagick binary.
    LetterAvatar.stubs(:version).returns('nonce-test')
    sign_in(buyer)
    get '/latest', headers: { 'HTTP_USER_AGENT' => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Accept' => 'text/html' }
    expect(response.status).to eq(200)
    scripts = Nokogiri::HTML(response.body).css('script[src*="forum-experience.js"]')
    expect(scripts.length).to eq(1)
    nonce = scripts.first['nonce']
    expect(nonce).to be_present
    expect(response.headers['Content-Security-Policy']).to include("'nonce-#{nonce}'")
  end

  it 'publishes previews while keeping paid work prompts out of forum and public JSON' do
    record = publish
    post = record.topic.posts.find_by!(post_number: 1)
    expect(post.raw).not_to include(secret)
    expect(post.cooked).not_to include(secret)
    expect(record.content.data['prompt']).to eq(secret)
    get "/studio/api/entries/#{record.public_id}.json"
    expect(response.status).to eq(200)
    expect(response.body).not_to include(secret)
    expect(response.parsed_body['price']).to eq(10)
    get "/t/#{record.topic_id}.json"
    expect(response.body).not_to include(secret)
    get "/studio/api/entries/#{record.public_id}/content.json"
    expect(response.status).to eq(403)
    sign_in(buyer)
    get "/studio/api/entries/#{record.public_id}/content.json"
    expect(response.status).to eq(403)
    grant
    2.times do
      post "/studio/api/entries/#{record.public_id}/unlock.json", params: { price: 10, price_revision: 1 }
      expect(response.status).to eq(200)
    end
    get "/studio/api/entries/#{record.public_id}/content.json"
    expect(response.status).to eq(200)
    expect(response.parsed_body.dig('content', 'prompt')).to eq(secret)
    expect(response.headers['Cache-Control']).to include('private', 'no-store')
    expect(Handraw::Wallet.for_user(buyer.id).balance).to eq(90)
    expect(record.unlocks.count).to eq(1)
  end

  it 'rejects self-collection through the unified asset endpoint' do
    record = publish('style', paid_opt_in: false)
    sign_in(author)
    post "/studio/api/assets/community%3A#{record.public_id}/collection.json"
    expect(response.status).to eq(422)
    expect(record.collections.count).to eq(0)
  end

  it 'keeps paid experience bodies out of post revisions and search results' do
    record = publish('experience')
    expect(record.topic.first_post.raw).not_to include(secret)
    expect(record.topic.first_post.post_revisions.map(&:as_json).to_json).not_to include(secret)
    sign_in(buyer)
    get '/search.json', params: { q: secret }
    expect(Array(response.parsed_body['posts']).to_json).not_to include(secret)
    get "/studio/api/entries/#{record.public_id}/content.json"
    expect(response.status).to eq(403)
  end

  it 'allows authors to publish free content without giving anonymous readers write access' do
    record = publish('experience', price: 0)
    get "/studio/api/entries/#{record.public_id}/content.json"
    expect(response.status).to eq(200)
    expect(response.parsed_body.dig('content', 'body')).to eq(secret)
    patch "/studio/api/entries/#{record.public_id}.json", params: { entry: { price: 20 } }
    expect(response.status).to eq(403)
  end

  it 'requires examples and an independent reviewer for template sales without forcing featured status' do
    record = publish('layout')
    expect(record.tradable?).to eq(false)
    sign_in(buyer)
    grant
    post "/studio/api/entries/#{record.public_id}/unlock.json", params: { price: 10, price_revision: 1 }
    expect(response.status).to eq(422)
    sign_in(reviewer)
    post "/studio/api/entries/#{record.public_id}/review.json", params: { action_name: 'verify', reason: '检查不同内容的复用效果' }
    expect(response.status).to eq(422)
    examples = 2.times.map { |i| { 'theme' => "主题#{i}", 'image' => "https://img.handraw-style.com/images/#{i}.png" } }
    record.update!(metadata: record.metadata.merge('examples' => examples))
    post "/studio/api/entries/#{record.public_id}/review.json", params: { action_name: 'verify', reason: '不同内容复用测试均已通过' }
    expect(response.status).to eq(200)
    expect(record.reload.download_approved).to eq(true)
    expect(record.featured).to eq(false)
    expect(Handraw::Wallet.for_user(author.id).balance).to eq(0)
  end

  it 'limits associations to two distinct styles and one layout and supports reverse discovery' do
    links = [{ ref: 'official:FA-001', role: 'character' }, { ref: 'official:FB-006', role: 'scene' }, { ref: 'official:SC-001', role: 'layout' }]
    record = publish('work', assets: links)
    expect(record.asset_links.count).to eq(3)
    get '/studio/api/assets/official:FA-001/related.json'
    expect(response.status).to eq(200)
    expect(response.parsed_body['works'].map { |r| r['id'] }).to include(record.public_id)
    expect { publish('work', assets: links + [{ ref: 'official:FC-029' }], content: { prompt: '另外一份不同的完整作品提示词。' }) }.to raise_error(Handraw::RuleError, /最多/)
    expect { Handraw::Catalog.links!(record, [{ ref: 'official:FA-001' }, { ref: 'official:FA-001' }]) }.to raise_error(Handraw::RuleError)
  end

  it 'does not unlock associated paid resources when buying a work' do
    style = publish('style')
    style.update!(download_approved: true)
    work = publish('work', assets: [{ ref: "community:#{style.public_id}" }])
    grant
    Handraw::Economy.unlock!(work, buyer, 10, 1)
    expect(work.content_readable?(buyer)).to eq(true)
    expect(style.content_readable?(buyer)).to eq(false)
    expect { Handraw::Creation.resolve(buyer, theme: '窗台上的一只小猫', style: "community:#{style.public_id}") }.to raise_error(Handraw::RuleError, /解锁/)
  end

  it 'keeps author fixed prices out of dynamic pricing and requires re-confirmation' do
    record = publish('experience')
    record.update!(created_at: 10.days.ago, download_approved: true)
    Handraw::Economy.reprice!(record)
    expect(record.reload.price).to eq(10)
    sign_in(author)
    patch "/studio/api/entries/#{record.public_id}.json", params: { entry: { price: 25 } }
    expect(response.status).to eq(200)
    expect(record.reload.price_revision).to eq(2)
    expect(record.topic.first_post.raw).not_to include(secret)
    grant
    expect { Handraw::Economy.unlock!(record, buyer, 10, 1) }.to raise_error(Handraw::RuleError, /价格/)
    expect { Handraw::Publishing.update!(record, author, price: 7) }.to raise_error(Handraw::RuleError)
  end

  it 'uses exact fusion control text and rejects double styles outside fusion mode' do
    creation = { theme: '山间溪流旁的一只小狐狸', fusion: true, character_style: 'FA-001', scene_style: 'FB-006', layout: 'SC-001', ratio: '3:4' }
    result = Handraw::Creation.resolve(author, creation)
    expect(result[:prompt]).to include('缩微摄影，角色尺寸异常小，场景保持正常尺寸。', '不要把两者平均磨成普通的混合风格插画。', '主题事件明确可读')
    expect(result[:assets].size).to eq(3)
    expect { Handraw::Creation.resolve(author, creation.merge(fusion: false)) }.to raise_error(Handraw::RuleError)
    expect { Handraw::Creation.resolve(author, creation.merge(scene_style: 'FA-001')) }.to raise_error(Handraw::RuleError)
    expect { Handraw::Creation.resolve(author, creation.merge(scene_style: 'official:FA-001')) }.to raise_error(Handraw::RuleError)
  end

  it 'allows verified non-pilot users to generate using server-resolved definitions' do
    SiteSetting.handraw_public_submissions = false
    sign_in(buyer)
    Handraw::ImageService.stubs(:enabled?).returns(true)
    Handraw::ImageService.stubs(:request).returns('status' => 'running')
    post '/studio/api/generations.json', params: { client_id: SecureRandom.uuid, creation: { theme: '窗台上的一只小猫', style: 'FA-001', ratio: '1:1' } }
    expect(response.status).to eq(200)
    task = Handraw::ImageService.store(buyer)['tasks'].first
    expect(task['prompt']).to include(Handraw::Catalog.find('FA-001')['definition'])
    expect(response.body).not_to include('核心风格特征')
  end

  it 'revokes content and rating qualification after refund without paying the author' do
    record = publish
    grant
    sale = Handraw::Economy.unlock!(record, buyer, 10, 1)
    record.events.create!(user: buyer, kind: 'useful', qualified: true, day: Date.current)
    sale.refund!(reviewer, '提示词描述严重不符，已核实')
    expect(record.content_readable?(buyer)).to eq(false)
    expect(record.events.first.reload.qualified).to eq(false)
    sale.settle!
    expect(Handraw::Wallet.for_user(author.id).balance).to eq(0)
  end

  it 'protects inline experience images through purchase and refund' do
    FileUtils.mkdir_p(Handraw::PrivateMedia.root)
    Tempfile.create(['handraw-inline', '.png']) do |file|
      file.binmode
      file.write("\x89PNG\r\n\x1a\n".b + 'private image bytes')
      file.flush
      upload = Struct.new(:tempfile).new(File.open(file.path, 'rb'))
      image = Handraw::PrivateMedia.save!(author, upload)
      upload.tempfile.close
      url = "/studio/api/private-images/#{image.public_id}"
      record = publish('experience', content: { body: "这是完整的收费经验正文。\n\n![正文配图](#{url})" })
      expect(image.reload.entry_id).to eq(record.id)
      get url
      expect(response.status).to eq(403)
      sign_in(reviewer)
      get url
      expect(response.status).to eq(200)
      expect(Handraw::Audit.where(user_id: reviewer.id, entry_id: record.id, action: 'inspect_private_image').count).to eq(1)
      sign_in(buyer)
      get url
      expect(response.status).to eq(403)
      grant
      sale = Handraw::Economy.unlock!(record, buyer, 10, 1)
      get url
      expect(response.status).to eq(200)
      expect(response.headers['Cache-Control']).to include('private', 'no-store')
      sale.refund!(reviewer, '正文严重不符，经版主核实')
      get url
      expect(response.status).to eq(403)
      File.delete(Handraw::PrivateMedia.path(image))
    end
  end

  it 'denies feedback on paid previews and preserves entitlements across updates' do
    record = publish
    sign_in(buyer)
    record.events.create!(user: buyer, kind: 'detail', qualified: true, day: Date.current)
    post "/studio/api/entries/#{record.public_id}/events.json", params: { kind: 'useful' }
    expect(response.status).to eq(422)
    grant
    Handraw::Economy.unlock!(record, buyer, 10, 1)
    get "/studio/api/entries/#{record.public_id}/content.json"
    post "/studio/api/entries/#{record.public_id}/events.json", params: { kind: 'useful' }
    expect(response.status).to eq(204)
    Handraw::Publishing.update!(record, author, content: { prompt: '更新后的完整提示词，仍对已购买用户免费开放。' }, version: '1.1.0')
    get "/studio/api/entries/#{record.public_id}/content.json"
    expect(response.status).to eq(200)
    expect(response.parsed_body['version']).to eq('1.1.0')
    expect(record.unlocks.count).to eq(1)
    expect(Handraw::Wallet.for_user(buyer.id).balance).to eq(90)
  end
end
