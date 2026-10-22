# frozen_string_literal: true

module Handraw
  class Entry < ActiveRecord::Base
    self.table_name = 'handraw_entries'

    KINDS = %w[work experience style layout package].freeze
    belongs_to :user
    belongs_to :topic
    has_many :collections, class_name: 'Handraw::Collection', dependent: :destroy
    has_many :events, class_name: 'Handraw::Event', dependent: :destroy
    has_many :unlocks, class_name: 'Handraw::Unlock', dependent: :restrict_with_error
    has_one :content, class_name: 'Handraw::Content', dependent: :destroy
    has_many :asset_links, class_name: 'Handraw::AssetLink', dependent: :destroy
    validates :kind, inclusion: { in: KINDS }
    validates :title, length: { in: 5..160 }
    validates :summary, length: { in: 10..4000 }
    validates :license, length: { in: 5..2000 }
    validates :public_id, :content_digest, presence: true, uniqueness: true
    before_validation :set_initial_price, on: :create

    scope :visible, lambda {
      joins(topic: :category).where(status: 'published')
                             .where(topics: { deleted_at: nil, archetype: 'regular', visible: true })
                             .where(categories: { read_restricted: false })
    }

    scope :image_works, lambda {
      where(kind: 'work').where("NULLIF(BTRIM(handraw_entries.cover_url), '') IS NOT NULL")
                         .where("handraw_entries.metadata ->> 'imported_from_forum' IS DISTINCT FROM 'true'")
    }
    scope :for_listing, -> { where.not(kind: 'work').or(image_works) }

    def bundled?
      bundle_key.present? && bundle_sha256.present?
    end

    def market?
      metadata['content_market'] == true
    end

    def resource?
      %w[style layout].include?(kind)
    end

    def tradable?
      status == 'published' && (market? ? content.present? && (!resource? || !paid_opt_in || download_approved) : bundled? && download_approved)
    end

    def content_readable?(viewer)
      return true if viewer&.id == user_id
      return false unless market? && tradable?
      return true unless paid_opt_in
      accessible_to?(viewer)
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
        paid: market? ? paid_opt_in : paid_opt_in && download_approved,
        price: paid_opt_in && (market? || download_approved) ? price : 0,
        pricing_mode: pricing_mode,
        market: market?,
        tradable: tradable?,
        review_pending: market? && resource? && paid_opt_in && !download_approved,
        content_available: market? && content.present?,
        price_revision: price_revision,
        price_reason: price_reason,
        bundle_available: bundled? && download_approved,
        collected: viewer ? collections.where(user_id: viewer.id).exists? : false,
        unlocked: market? ? content_readable?(viewer) : accessible_to?(viewer),
        ref: resource? ? "community:#{public_id}" : nil,
        assets: asset_links.map do |link|
          asset = Catalog.find(link.asset_ref) rescue nil
          { ref: link.asset_ref, kind: link.kind, role: link.role, version: link.version,
            name: asset.is_a?(Entry) ? asset.title : asset&.dig('name'),
            available: asset.present? }
        end,
        examples: Array(metadata['examples']),
        collection_count: collections.count,
        created_at: created_at,
        source_label: metadata['imported_from_forum'] ? '来自论坛' : nil
      }
    end

    def qualified_events
      events.where(qualified: true)
    end

    def exploration_limit
      visitors = qualified_events.where(kind: 'detail').distinct.count(:user_id)
      collectors = collections.joins(:user).where(users: { active: true, staged: false }).count
      if visitors >= SiteSetting.handraw_exploration_detail_threshold || collectors.positive?
        SiteSetting.handraw_exploration_extended
      else
        SiteSetting.handraw_exploration_initial
      end
    end

    def exploring?
      qualified_events.where(kind: 'impression').distinct.count(:user_id) < exploration_limit
    end

    def quality_score
      impressions = qualified_events.where(kind: 'impression').distinct.count(:user_id)
      visitors = qualified_events.where(kind: 'detail').distinct.count(:user_id)
      saved = collections.joins(:user).where(users: { active: true, staged: false }).count
      votes = qualified_events.where(kind: %w[useful not_useful])
      useful = votes.where(kind: 'useful').count
      save_rate = (saved + 1.0) / ([visitors, saved].max + 10)
      useful_rate = (useful + 2.0) / (votes.count + 4)
      (kind == 'work' ? save_rate * 0.7 + useful_rate * 0.3 : save_rate * 0.3 + useful_rate * 0.7) +
        [visitors.to_f / (impressions + 10), 1].min * 0.01
    end

    private

    def set_initial_price
      return if price_changed?

      lower = SiteSetting.handraw_price_min
      upper = [SiteSetting.handraw_price_max, lower].max
      self.price = SiteSetting.handraw_price_initial.clamp(lower, upper)
    end
  end
end
