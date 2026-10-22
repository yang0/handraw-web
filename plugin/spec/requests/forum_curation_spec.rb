# frozen_string_literal: true

require 'rails_helper'

RSpec.describe 'Forum experience curation and guide links' do
  fab!(:author) { Fabricate(:user, active: true, created_at: 20.days.ago) }
  fab!(:reader) { Fabricate(:user, active: true, created_at: 20.days.ago) }
  fab!(:reviewer) { Fabricate(:admin, active: true) }
  let!(:source_post) { Fabricate(:post, user: author, raw: '先选择画风，记录提示词，再展示结果。这篇方法直接在论坛原帖中维护。') }
  let(:topic) { source_post.topic }
  let(:endpoint) { "/studio/api/topics/#{topic.id}/experience.json" }

  before do
    [author, reader, reviewer].each { |user| user.activate unless user.email_confirmed? }
    SiteSetting.handraw_enabled = true
    SiteSetting.handraw_public_submissions = true
  end

  it 'allows only an independent reviewer to mark a forum post' do
    post endpoint
    expect(response.status).to eq(403)
    sign_in(reader)
    post endpoint
    expect(response.status).to eq(403)
    author.update!(admin: true)
    sign_in(author)
    post endpoint
    expect(response.status).to eq(422)
    expect(Handraw::Entry.count).to eq(0)
  end

  it 'links to the original post with its author and creates no duplicate post or protected body' do
    sign_in(reviewer)
    expect { 2.times { post endpoint; expect(response.status).to eq(200) } }.not_to change(Post, :count)
    record = Handraw::Entry.find_by!(topic_id: topic.id)
    expect(record.user_id).to eq(author.id)
    expect(record.content).to be_nil
    expect(record.forum_curated?).to eq(true)
    expect(record.price).to eq(0)
    expect(record.paid_opt_in).to eq(false)
    expect(record.summary).to include('直接在论坛原帖中维护')
    expect(Handraw::Entry.where(topic_id: topic.id).count).to eq(1)
    expect(Handraw::Audit.where(entry_id: record.id, action: 'curate_experience').count).to eq(1)
    expect(Handraw::Ledger.count).to eq(0)
    get '/studio/api/feed.json', params: {kind: 'experience'}
    row = response.parsed_body['entries'].find { |e| e['id'] == record.public_id }
    expect(row).to include('forum_curated' => true, 'topic_url' => "/t/#{topic.id}", 'price' => 0)
    expect(source_post.reload.raw).to include('直接在论坛原帖中维护')
  end

  it 'can reverse and restore the mark without deleting the original post or contribution record' do
    sign_in(reviewer)
    post endpoint
    id = response.parsed_body.dig('entry', 'id')
    2.times { delete endpoint; expect(response.status).to eq(204) }
    record = Handraw::Entry.find_by!(public_id: id)
    expect(record.status).to eq('hidden')
    expect(Topic.exists?(topic.id)).to eq(true)
    expect(Post.exists?(source_post.id)).to eq(true)
    expect(Handraw::Audit.where(entry_id: record.id, action: 'uncurate_experience').count).to eq(1)
    post endpoint
    expect(response.parsed_body.dig('entry', 'id')).to eq(id)
    expect(record.reload.status).to eq('published')
  end

  it 'rejects private topics and hidden first posts even for reviewers' do
    sign_in(reviewer)
    topic.category.update!(read_restricted: true)
    post endpoint
    expect(response.status).to eq(403)
    topic.category.update!(read_restricted: false)
    source_post.update!(hidden: true)
    post endpoint
    expect(response.status).to eq(403)
    expect(Handraw::Entry.count).to eq(0)
  end

  it 'retains the existing two-style and one-layout association limit' do
    sign_in(reviewer)
    links = [{ref: 'official:FA-001'}, {ref: 'official:FB-006'}, {ref: 'official:SC-001'}]
    post endpoint, params: {assets: links + [{ref:'official:FC-029'}]}
    expect(response.status).to eq(422)
    expect(Handraw::Entry.count).to eq(0)
    post endpoint, params: {assets: links}
    expect(response.status).to eq(200)
    expect(Handraw::Entry.find_by!(topic_id: topic.id).asset_links.count).to eq(3)
  end

  it 'rejects direct experience submissions and edits to curated entries' do
    sign_in(reviewer)
    post '/studio/api/entries.json', params: {entry:{kind:'experience', title:'不再单独发布的经验正文', summary:'经验应在论坛维护，然后由独立版主收录。', content:{body:'经验应在论坛维护，然后由独立版主收录。'}}}
    expect(response.status).to eq(422)
    expect(response.parsed_body['errors'].join).to include('版主')
    post endpoint
    id = response.parsed_body.dig('entry','id')
    sign_in(author)
    patch "/studio/api/entries/#{id}.json", params:{entry:{price:20}}
    expect(response.status).to eq(422)
    expect(Handraw::Entry.find_by!(public_id:id).price).to eq(0)
  end

  it 'lets feedback reward the original author without rewarding the moderator for marking' do
    sign_in(reviewer)
    post endpoint
    id = response.parsed_body.dig('entry','id')
    sign_in(reader)
    post "/studio/api/entries/#{id}/events.json", params:{kind:'detail'}
    post "/studio/api/entries/#{id}/events.json", params:{kind:'useful'}
    expect(response.status).to eq(204)
    expect(Handraw::Entry.find_by!(public_id:id).events.where(kind:'useful',qualified:true).count).to eq(1)
    expect(Handraw::Wallet.for_user(reviewer.id).balance).to eq(0)
  end

  it 'aggregates only visible guide topics as links and summaries without a second body' do
    hidden = Fabricate(:post)
    hidden.topic.update!(visible:false)
    Handraw::Editorial.stubs(:configuration).returns('guides' => [
      {'id'=>'start','topic_id'=>topic.id,'summary'=>'安装与首次创作的操作步骤。'},
      {'id'=>'hidden','topic_id'=>hidden.topic_id,'summary'=>'不能出现在公开指南中的说明。'}
    ])
    get '/studio/api/boot.json'
    expect(response.status).to eq(200)
    guides=response.parsed_body.dig('editorial','guides')
    expect(guides.size).to eq(1)
    expect(guides.first).to include('title'=>topic.title,'url'=>"/t/#{topic.id}",'summary'=>'安装与首次创作的操作步骤。')
    expect(guides.first.keys).not_to include('steps','body')
  end
end
