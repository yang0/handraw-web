# frozen_string_literal: true

require 'nokogiri'
require 'cgi'

raise 'Wrong database' unless ActiveRecord::Base.connection.current_database == 'discourse'

sources = { 235 => 'work', 17 => 'experience', 19 => 'experience', 18 => 'experience',
            233 => 'experience', 234 => 'experience' }
created = []
Handraw::Entry.transaction do
  sources.each do |topic_id, kind|
    next if Handraw::Entry.exists?(topic_id: topic_id)

    topic = Topic.find(topic_id)
    raise "Source #{topic_id} is not public" unless topic.visible && topic.deleted_at.nil? &&
      topic.archetype == 'regular' && topic.category && !topic.category.read_restricted

    post = topic.posts.find_by!(post_number: 1, deleted_at: nil)
    document = Nokogiri::HTML.fragment(post.cooked)
    text = CGI.unescapeHTML(document.text).gsub(/\s+/, ' ').strip
    image = document.css('img').filter_map { |node| node['src'] }.find do |url|
      url.start_with?('/uploads/', 'https://static.handraw-style.com/', 'https://img.handraw-style.com/',
                      'https://handraw-style.com/uploads/')
    end
    record = Handraw::Entry.create!(
      user_id: post.user_id, topic_id: topic.id, public_id: SecureRandom.uuid, kind: kind,
      title: topic.title, summary: text.first(800), cover_url: image.to_s,
      license: '原帖公开展示，保留原作者署名；使用、商用及转载请联系原作者。',
      content_digest: Digest::SHA256.hexdigest("existing-public-topic:#{topic.id}"),
      created_at: post.created_at, metadata: { imported_from_forum: true, original_post_id: post.id }
    )
    created << { id: record.public_id, topic_id: topic.id, username: post.user.username, kind: kind }
  end
end
puts JSON.generate(created: created, existing_sources: sources.keys, new_forum_posts: 0, automatic_credit_awards: 0)
