# frozen_string_literal: true

module Handraw
  class Entry < ActiveRecord::Base
    self.table_name = "handraw_entries"

    KINDS = %w[work experience style layout package].freeze
    belongs_to :user
    belongs_to :topic
    has_many :collections, class_name: "Handraw::Collection", dependent: :destroy
    has_many :events, class_name: "Handraw::Event", dependent: :destroy
    has_many :unlocks, class_name: "Handraw::Unlock", dependent: :restrict_with_error
    validates :kind, inclusion: { in: KINDS }
    validates :title, length: { in: 5..160 }
    validates :summary, length: { in: 10..4000 }
    validates :license, length: { in: 5..2000 }
    validates :public_id, :content_digest, presence: true, uniqueness: true

    scope :visible, -> {
      joins(topic: :category).where(status: "published")
        .where(topics: { deleted_at: nil, archetype: "regular", visible: true })
        .where(categories: { read_restricted: false })
    }

    def bundled?
      bundle_key.present? && bundle_sha256.present?
    end

    def accessible_to?(viewer)
      viewer && (viewer.id == user_id || unlocks.where(user_id: viewer.id, refunded_at: nil).exists?)
    end

    def public_payload(viewer = nil)
      {
        id: public_id,
        kind: kind,
        title: title,
        summary: summary,
        cover_url: cover_url,
        author: { id: user_id, username: user.username, name: user.name },
        topic_url: "/t/#{topic_id}",
        version: version,
        license: license,
        featured: featured,
        verified: verified,
        paid: paid_opt_in && download_approved,
        price: download_approved && paid_opt_in ? price : 0,
        price_revision: price_revision,
        price_reason: price_reason,
        bundle_available: bundled? && download_approved,
        collected: viewer ? collections.where(user_id: viewer.id).exists? : false,
        unlocked: accessible_to?(viewer),
        collection_count: collections.count,
        created_at: created_at,
      }
    end

    def qualified_events
      events.where(qualified: true)
    end

    def exploration_limit
      visitors = qualified_events.where(kind: "detail").distinct.count(:user_id)
      collectors = collections.joins(:user).where(users: { active: true, staged: false }).count
      if visitors >= 2 || collectors.positive?
        SiteSetting.handraw_exploration_extended
      else
        SiteSetting.handraw_exploration_initial
      end
    end

    def exploring?
      qualified_events.where(kind: "impression").distinct.count(:user_id) < exploration_limit
    end

    def quality_score
      impressions = qualified_events.where(kind: "impression").distinct.count(:user_id)
      visitors = qualified_events.where(kind: "detail").distinct.count(:user_id)
      saved = collections.joins(:user).where(users: { active: true, staged: false }).count
      votes = qualified_events.where(kind: %w[useful not_useful])
      useful = votes.where(kind: "useful").count
      ((saved + 1.0) / ([visitors, saved].max + 10) +
        (useful + 2.0) / (votes.count + 4)) / 2 +
        [visitors.to_f / (impressions + 10), 1].min * 0.01
    end
  end
end
