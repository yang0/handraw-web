# frozen_string_literal: true

module Handraw
  module Feed
    def self.call(kind: nil, page: 1, search: nil)
      scope = Entry.visible.includes(:user)
      scope = scope.where(kind: kind) if Entry::KINDS.include?(kind)
      if search.present?
        pattern = "%#{Entry.sanitize_sql_like(search.to_s.first(100))}%"
        scope = scope.where('handraw_entries.title ILIKE :query OR handraw_entries.summary ILIKE :query',
                            query: pattern)
      end
      page = [[page.to_i, 1].max, 50].min
      candidates = scope.order(created_at: :desc).limit(500).to_a
      counts = Event.where(entry_id: candidates.map(&:id), qualified: true).group(:entry_id,
                                                                                  :kind).distinct.count(:user_id)
      saves = Collection.where(entry_id: candidates.map(&:id)).joins(:user)
                        .where(users: { active: true, staged: false }).group(:entry_id).count
      exploration = lambda { |entry|
        limit = if counts.fetch([entry.id, 'detail'], 0) >= 2 || saves.fetch(entry.id, 0).positive?
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
      pattern = %i[quality explore quality featured quality explore quality featured quality explore]
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
