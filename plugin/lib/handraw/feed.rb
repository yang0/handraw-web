# frozen_string_literal: true

module Handraw
  module Feed
    def self.call(kind: nil, page: 1, search: nil)
      scope = Entry.visible.includes(:user, :collections, :events)
      scope = scope.where(kind: kind) if Entry::KINDS.include?(kind)
      if search.present?
        pattern = "%#{Entry.sanitize_sql_like(search.to_s.first(100))}%"
        scope = scope.where("handraw_entries.title ILIKE :query OR handraw_entries.summary ILIKE :query", query: pattern)
      end
      page = [[page.to_i, 1].max, 50].min
      candidates = scope.order(created_at: :desc).limit(500).to_a
      exploring = candidates.select(&:exploring?).sort_by(&:created_at).uniq(&:user_id)
      quality = candidates.reject(&:exploring?).sort_by { |entry| -entry.quality_score }
      featured = candidates.select(&:featured).sort_by { |entry| -entry.quality_score }
      queues = { quality: diversify(quality), explore: diversify(exploring), featured: diversify(featured) }
      pattern = %i[quality explore quality featured quality explore quality featured quality explore]
      chosen = []
      authors = Hash.new(0)
      fallback = diversify(candidates)
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
