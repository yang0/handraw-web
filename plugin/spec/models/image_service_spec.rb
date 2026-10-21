# frozen_string_literal: true

require 'rails_helper'

RSpec.describe Handraw::ImageService do
  fab!(:author) { Fabricate(:user) }
  fab!(:other) { Fabricate(:user) }

  before do
    described_class.stubs(:enabled?).returns(true)
    SiteSetting.handraw_generation_daily_limit = 3
  end

  def submit(client_id = SecureRandom.uuid, prompt = '一只趴在窗台上的小猫')
    described_class.submit(author, client_id: client_id, prompt: prompt, title: '窗台小猫', ratio: '3:4')
  end

  it 'keeps one task and one quota entry across retried submissions' do
    ids = []
    described_class.stubs(:request).with do |_path, payload:|
      ids << payload[:client_task_id]
      payload[:size] == '1152x1536'
    end.returns('status' => 'queued')
    key = SecureRandom.uuid
    first = submit(key)
    second = submit(key)
    expect(second['id']).to eq(first['id'])
    expect(ids.uniq).to eq([first['id']])
    expect(described_class.store(author)['submitted']).to eq(1)
  end

  it 'rejects a changed payload under the same idempotency key' do
    described_class.stubs(:request).returns('status' => 'running')
    key = SecureRandom.uuid
    submit(key)
    expect { submit(key, '一条不同主题的提示词') }.to raise_error(Handraw::RuleError)
  end

  it 'enforces one unfinished generation and the daily submission allowance' do
    described_class.stubs(:request).returns('status' => 'running')
    first = submit
    expect { submit }.to raise_error(Handraw::RuleError, /正在生成/)
    described_class.update(author, first['id'], 'status' => 'error')
    SiteSetting.handraw_generation_daily_limit = 1
    expect { submit }.to raise_error(Handraw::RuleError, /今天/)
    expect(described_class.store(author)['submitted']).to eq(1)
  end

  it 'does not expose another user history or allow confirmation or image access' do
    described_class.stubs(:request).returns('status' => 'running')
    first = submit
    expect(described_class.list(other)[:tasks]).to eq([])
    expect { described_class.dispatch(other, first['id']) }.to raise_error(Discourse::NotFound)
    expect { described_class.image(other, first['id'], '0') }.to raise_error(Discourse::NotFound)
  end

  it 'publishes only authenticated image routes and resists stale status updates' do
    described_class.stubs(:request).returns('status' => 'running')
    first = submit
    result = described_class.update(author, first['id'], 'status' => 'success', 'data' => [
                                     { 'url' => 'https://chatgpt2api.handraw-style.com/images/example.png' },
                                     { 'url' => 'http://169.254.169.254/latest/meta-data/' }
                                   ])
    expect(result['images']).to eq(["/studio/api/generations/#{first['id']}/image?index=0"])
    expect(result).not_to have_key('prompt')
    expect(result).not_to have_key('urls')
    expect(described_class.update(author, first['id'], 'status' => 'queued')['status']).to eq('success')
  end

  it 'retains the task key for explicit confirmation after a network timeout' do
    described_class.stubs(:request).raises(Handraw::RuleError, '暂时无法确认生图任务')
    first = submit
    expect(first['status']).to eq('queued')
    expect(first['message']).to include('暂时无法确认')
    expect(described_class.store(author)['submitted']).to eq(1)
  end
end
