# frozen_string_literal: true

module Handraw
  module Catalog
    def self.official
      @official ||= JSON.parse(File.read(Handraw::Engine.root.join('content/catalog.json')))['resources']
    end

    def self.find(ref)
      value = ref.to_s.delete_prefix('official:')
      if value.start_with?('community:')
        Entry.visible.where(kind: %w[style layout]).find_by!(public_id: value.delete_prefix('community:'))
      else
        official.find { |item| item['id'] == value && %w[style layout color].include?(item['kind']) } || raise(Discourse::NotFound)
      end
    end

    def self.ref(asset)
      asset.is_a?(Entry) ? "community:#{asset.public_id}" : "official:#{asset.fetch('id')}"
    end

    def self.payload(asset, viewer = nil)
      if asset.is_a?(Entry)
        asset.public_payload(viewer).merge(ref: ref(asset), source: 'community', name: asset.title,
                                          description: asset.summary, image: asset.cover_url)
      else
        asset.except('definition').merge('ref' => ref(asset), 'source' => 'official', 'price' => 0,
                                         'version' => '1.0.0', 'unlocked' => true, 'tradable' => true,
                                         'author' => { 'name' => '手绘风官方' }, 'license' => '沿用官方 Skill 的使用说明')
      end
    end

    def self.definition(asset, viewer)
      if asset.is_a?(Entry)
        raise RuleError, '请先解锁所选画风或图型，再开始创作' unless asset.content_readable?(viewer)
        data = asset.content.data
        data['definition_zh'].presence || data['definition'].presence || raise(RuleError, '画风或图型定义尚未补全')
      else
        asset['definition'].presence || asset['description']
      end
    end

    def self.links!(entry, inputs)
      raise RuleError, '关联资产必须是列表' unless inputs.nil? || inputs.is_a?(Array)
      rows = Array(inputs).map do |input|
        item = input.respond_to?(:to_unsafe_h) ? input.to_unsafe_h : input
        raise RuleError, '关联资产格式无效' unless item.is_a?(Hash)
        asset = find(item['ref'] || item[:ref])
        kind = asset.is_a?(Entry) ? asset.kind : asset['kind']
        raise RuleError, '只能关联画风或图型' unless %w[style layout].include?(kind)
        version = asset.is_a?(Entry) ? asset.version : '1.0.0'
        { asset_ref: ref(asset), kind: kind, role: (item['role'] || item[:role]).to_s, version: version }
      end
      if rows.count { |r| r[:kind] == 'style' } > 2 || rows.count { |r| r[:kind] == 'layout' } > 1 || rows.map { |r| r[:asset_ref] }.uniq.size != rows.size
        raise RuleError, '最多关联两个不同画风和一个图型'
      end
      raise RuleError, '只有作品和经验可以关联资产' if rows.any? && !%w[work experience].include?(entry.kind)
      rows.each do |r|
        r[:role] = r[:kind] if r[:role].blank?
        raise RuleError, '关联角色无效' unless %w[style character scene layout].include?(r[:role])
        raise RuleError, '关联角色与资产类型不一致' if (r[:kind] == 'layout') != (r[:role] == 'layout')
      end
      entry.asset_links.destroy_all
      rows.each { |row| entry.asset_links.create!(row) }
    end
  end
end
