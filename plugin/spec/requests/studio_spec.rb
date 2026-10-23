# frozen_string_literal: true
require 'rails_helper'

RSpec.describe 'Full studio creation' do
  fab!(:author) { Fabricate(:user, active:true) }
  fab!(:other) { Fabricate(:user, active:true) }
  let(:creation) { {theme:'窗台晒太阳的小猫咪',style:'FA-001',ratio:'5:2',mode:'poster',whitespace:'high',tones:%w[T-01 T-04],audience:'亲子家庭',channel:'线下海报',mood:'松弛、治愈',extra:'主标题使用中文',quality:'high'} }
  before do
    [author,other].each { |u| u.activate unless u.email_confirmed? }
    SiteSetting.handraw_enabled = true
    SiteSetting.handraw_public_submissions = true
    Handraw::ImageService.stubs(:enabled?).returns(true)
  end

  it 'previews official prompts anonymously and resolves every selected control on the server' do
    post '/studio/api/creation/resolve.json', params:{creation:creation}
    expect(response.status).to eq(200)
    prompt=response.parsed_body['prompt']
    expect(prompt).to include('亲子家庭','线下海报','高调','软调','大量留白','松弛、治愈','主标题使用中文')
    expect(prompt).not_to include('#FA-001','核心风格特征')
    expect(response.parsed_body['plans'].size).to eq(1)
    expect(Handraw::ImageService.size_for('5:2')).to eq('1536x608')
    expect(Handraw::ImageService.size_for('')).to eq('auto')
    expect { Handraw::ImageService.size_for('0:1') }.to raise_error(Handraw::RuleError)
  end

  it 'preserves realistic fusion and applies exactly one selected SC-021 design' do
    result=Handraw::Creation.resolve(author,creation.merge(fusion:true,character_style:'realistic',scene_style:'FA-001',mode:'pure',layout:'SC-021',layout_variant:4))
    expect(result[:prompt]).to include('微缩浮岛型','左右双拼','写实摄影','不要把两者平均磨成普通的混合风格插画')
    expect(result[:prompt]).not_to include('视线锚点跨界续绘型')
    expect { Handraw::Creation.resolve(author,creation.merge(tones:['T-invalid'])) }.to raise_error(Handraw::RuleError)
  end

  it 'builds per-image themes and layouts instead of sending a batch instruction to an image model' do
    plans=Handraw::Creation.plans(author,creation.merge(batch:true,count:2,themes:['清晨花园里的小狐狸','夜晚森林中的猫头鹰'],mix_layouts:true,layouts:%w[SC-001 IG-001]))
    expect(plans.map { |p| p[:title] }).to eq(['清晨花园里的小狐狸','夜晚森林中的猫头鹰'])
    expect(plans.map { |p| p[:assets].last[:ref] }).to eq(%w[official:SC-001 official:IG-001])
    expect { Handraw::Creation.plans(author,creation.merge(batch:true,count:6)) }.to raise_error(Handraw::RuleError)
  end

  it 'books batch quota atomically, retries once, waits for known completion, and cancels only unstarted work' do
    plans=Handraw::Creation.plans(author,creation.merge(batch:true,count:3))
    Handraw::ImageService.stubs(:request).returns({'status'=>'running'})
    id=SecureRandom.uuid
    tasks=Handraw::ImageService.submit_batch(author,client_id:id,plans:plans)
    expect(tasks.map { |t| t['status'] }).to eq(%w[running waiting waiting])
    Handraw::ImageService.submit_batch(author,client_id:id,plans:plans)
    expect(Handraw::ImageService.store(author)['submitted']).to eq(3)
    expect { Handraw::ImageService.submit_batch(author,client_id:SecureRandom.uuid,plans:plans) }.to raise_error(Handraw::RuleError)
    Handraw::ImageService.stubs(:request).returns({'items'=>[]})
    Handraw::ImageService.list(author,refresh:true)
    expect(Handraw::ImageService.store(author)['tasks'].map { |t| t['status'] }).to eq(%w[running waiting waiting])
    Handraw::ImageService.update(author,tasks[0]['id'],{'status'=>'success','data'=>[{'url'=>'https://chatgpt2api.handraw-style.com/images/test.png'}]})
    Handraw::ImageService.stubs(:request).returns({'status'=>'running'})
    Handraw::ImageService.list(author,refresh:true)
    expect(Handraw::ImageService.store(author)['tasks'].map { |t| t['status'] }).to eq(%w[success running waiting])
    2.times { Handraw::ImageService.cancel_waiting(author,id) }
    expect(Handraw::ImageService.store(author)['submitted']).to eq(2)
    expect(Handraw::ImageService.store(author)['tasks'][1]['status']).to eq('running')
  end

  it 'uses the edit task endpoint for owned reference bytes and rejects another user before reservation' do
    Tempfile.create(['studio-reference','.png']) do |f|
      bytes="\x89PNG\r\n\x1a\n".b+'synthetic-isolated-fixture'
      f.binmode;f.write(bytes);f.flush
      upload=Struct.new(:tempfile).new(File.open(f.path,'rb'))
      image=Handraw::PrivateMedia.save!(author,upload);upload.tempfile.close
      input=creation.merge(references:[{id:image.public_id,role:'redraw',name:'reference.png'}])
      expect { Handraw::Creation.resolve(other,input) }.to raise_error(ActiveRecord::RecordNotFound)
      resolved=Handraw::Creation.resolve(author,input)
      expect(resolved[:prompt]).to include('不要在原照片上加质感')
      Handraw::ImageService.expects(:request).with('/api/image-tasks/edits',payload:has_entries(images:[{b64_json:Base64.strict_encode64(bytes),mime_type:'image/png'}],quality:'high',size:'1536x608')).returns({'status'=>'running'})
      Handraw::ImageService.submit(author,client_id:SecureRandom.uuid,prompt:resolved[:prompt],title:resolved[:title],ratio:resolved[:ratio],creation:resolved.except(:prompt))
      File.delete(Handraw::PrivateMedia.path(image))
    end
  end

  it 'does not pretend that online generation can read a local article path' do
    expect { Handraw::Creation.resolve(author,creation.merge(mode:'article-cover',theme:'E:/articles/guide.md')) }.to raise_error(Handraw::RuleError,/粘贴文章/)
    result=Handraw::Creation.resolve(author,creation.merge(mode:'article-cover',theme:'一篇关于阅读和学习的完整文章内容。',layout:'SC-001'))
    expect(result[:prompt]).to include('文章封面')
    expect(result[:assets].map { |r| r[:kind] }).not_to include('layout')
  end
end
