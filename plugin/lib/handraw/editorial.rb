# frozen_string_literal: true

module Handraw
  module Editorial
    def self.configuration
      JSON.parse(File.read(Handraw::Engine.root.join('content', 'editorial.json')))
    end

    def self.payload
      data = configuration
      topics = Topic.joins(:category).where(id: data['guides'].map { |guide| guide['topic_id'] },
                                           visible: true, deleted_at: nil, archetype: 'regular')
                    .where(categories: { read_restricted: false }).includes(:first_post).index_by(&:id)
      data['guides'] = data['guides'].filter_map do |guide|
        topic = topics[guide['topic_id']]
        next unless topic && topic.first_post && !topic.first_post.deleted_at && !topic.first_post.hidden
        guide.slice('id', 'summary').merge('title' => topic.title, 'url' => "/t/#{topic.id}", 'topic_id' => topic.id)
      end
      data
    end
  end
end
