# frozen_string_literal: true

require 'nokogiri'
require 'cgi'

module Handraw
  module ForumCuration
    def self.mark!(topic, reviewer, guardian, assets: nil)
      raise Discourse::InvalidAccess unless Access.reviewer?(reviewer)
      guardian.ensure_can_see!(topic)
      topic.with_lock do
        post = public_post!(topic)
        raise RuleError, '不能收录自己的帖子，请由其他版主处理' if post.user_id == reviewer.id
        record = Entry.find_by(topic_id: topic.id)
        raise RuleError, '此帖已关联其他投稿，不能改为经验' if record && (record.kind != 'experience' || record.market?)
        raise RuleError, '该经验已被暂停或隐藏，请先在审核台处理' if record && record.status != 'published' && !record.metadata['curation_removed']
        return record if record && record.status == 'published' && assets.nil?

        document = Nokogiri::HTML.fragment(post.cooked)
        summary = CGI.unescapeHTML(document.text).gsub(/\s+/, ' ').strip.first(800)
        raise RuleError, '请先完善原帖内容，再收录为经验' if summary.length < 10
        record ||= Entry.new(user_id: post.user_id, topic: topic, public_id: SecureRandom.uuid,
                             kind: 'experience', content_digest: Digest::SHA256.hexdigest("forum-experience:#{topic.id}"),
                             license: '保留原作者署名，使用与转载请遵循原帖授权并联系原作者。', price: 0,
                             pricing_mode: 'free', paid_opt_in: false, created_at: post.created_at)
        record.assign_attributes(title: topic.title.first(160), summary: summary, status: 'published',
                                 metadata: record.metadata.merge('forum_curated' => true, 'curation_removed' => false, 'original_post_id' => post.id))
        record.save!
        Catalog.links!(record, assets) unless assets.nil?
        Audit.create!(user_id: reviewer.id, entry_id: record.id, action: 'curate_experience',
                      reason: '从公开论坛原帖收录经验', details: { topic_id: topic.id })
        record
      end
    end

    def self.unmark!(topic, reviewer, guardian)
      raise Discourse::InvalidAccess unless Access.reviewer?(reviewer)
      guardian.ensure_can_see!(topic)
      topic.with_lock do
        post = public_post!(topic)
        raise RuleError, '不能审核自己的经验，请由其他版主处理' if post.user_id == reviewer.id
        record = Entry.find_by!(topic_id: topic.id, kind: 'experience')
        raise RuleError, '旧版独立经验请在审核台处理' unless record.forum_curated?
        return record if record.metadata['curation_removed']
        record.update!(status: 'hidden', metadata: record.metadata.merge('curation_removed' => true))
        Audit.create!(user_id: reviewer.id, entry_id: record.id, action: 'uncurate_experience',
                      reason: '取消论坛经验收录，保留原帖与贡献记录', details: { topic_id: topic.id })
        record
      end
    end

    def self.public_post!(topic)
      raise Discourse::InvalidAccess unless topic.visible && !topic.deleted_at && topic.archetype == 'regular' && topic.category && !topic.category.read_restricted
      post = topic.posts.find_by!(post_number: 1, deleted_at: nil)
      raise Discourse::InvalidAccess if post.hidden
      post
    end
  end
end
