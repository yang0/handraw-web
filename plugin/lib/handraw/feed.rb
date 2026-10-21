# frozen_string_literal: true

module Handraw
  module Feed
    def self.call(kind: nil, page: 1, search: nil, sort: nil)
      scope = Entry.visible.includes(:user)
      scope = scope.where(kind: kind) if Entry::KINDS.include?(kind)
      scope = scope.where(kind: %w[style layout package]) if kind == 'resource'
      if search.present?
        pattern = "%#{Entry.sanitize_sql_like(search.to_s.first(100))}%"
        scope = scope.where('handraw_entries.title ILIKE :query OR handraw_entries.summary ILIKE :query',
                            query: pattern)
      end
      page = [[page.to_i, 1].max, 50].min
      return scope.order(created_at: :desc).offset((page - 1) * 20).limit(20).to_a if search.present? || sort == 'latest'

      candidates = scope.order(created_at: :desc).limit(500).to_a
      counts = Event.where(entry_id: candidates.map(&:id), qualified: true).group(:entry_id,
                                                                                  :kind).distinct.count(:user_id)
      saves = Collection.where(entry_id: candidates.map(&:id)).joins(:user)
                        .where(users: { active: true, staged: false }).group(:entry_id).count
      exploration = lambda { |entry|
        limit = if counts.fetch([entry.id, 'detail'], 0) >= SiteSetting.handraw_exploration_detail_threshold || saves.fetch(entry.id, 0).positive?
                  SiteSetting.handraw_exploration_extended
                else
                  SiteSetting.handraw_exploration_initial
                end
        counts.fetch([entry.id, 'impression'], 0) < limit
      }
      score = lambda { |entry|
        saved = saves.fetch(entry.id, 0)
        visitors = counts.fetch([entry.id, 'detail'], 0)
        useful = counts.fetch([entry.id, 'useful'], 0)
        votes = useful + counts.fetch([entry.id, 'not_useful'], 0)
        ((saved + 1.0) / ([visitors, saved].max + 10) + (useful + 2.0) / (votes + 4)) / 2
      }
      exploring = candidates.select(&exploration).sort_by(&:created_at).uniq(&:user_id)
      quality = candidates.reject(&exploration).sort_by { |entry| -score.call(entry) }
      featured = candidates.select(&:featured).sort_by { |entry| -score.call(entry) }
      queues = { quality: diversify(quality), explore: diversify(exploring), featured: diversify(featured) }
      weights = { quality: SiteSetting.handraw_feed_quality_weight,
                  explore: SiteSetting.handraw_feed_explore_weight,
                  featured: SiteSetting.handraw_feed_featured_weight }
      progress = Hash.new(0)
      pattern = Array.new(weights.values.sum) do
        weights.each { |bucket, weight| progress[bucket] += weight }
        bucket = progress.max_by { |_key, value| value }.first
        progress[bucket] -= weights.values.sum
        bucket
      end
      chosen = []
      authors = Hash.new(0)
      fallback = diversify((quality + exploring + featured).uniq)
      pattern.cycle.take(page * 20).each do |bucket|
        entry = (queues[bucket] + fallback).find { |item| !chosen.include?(item) && authors[item.user_id] < 2 }
        next unless entry

        chosen << entry
        authors[entry.user_id] += 1
        authors.clear if chosen.size % 20 == 0
      end
      chosen.slice((page - 1) * 20, 20) || []
    end

    def self.diversify(entries)
      groups = entries.group_by(&:kind)
      result = []
      loop do
        batch = groups.values.filter_map(&:shift)
        break if batch.empty?

        result.concat(batch)
      end
      result
    end
  end
end
