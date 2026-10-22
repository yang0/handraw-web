# frozen_string_literal: true

module Handraw
  module Creation
    MODES = %w[pure graphic-text poster article-cover article-illust photo].freeze

    def self.resolve(user, values)
      input = Publishing.hash(values).stringify_keys
      mode = input['mode'].to_s.presence || 'pure'
      raise RuleError, '创作类型无效' unless MODES.include?(mode)
      theme = input['theme'].to_s.strip
      raise RuleError, '请用至少五个字描述主题' unless theme.length.between?(5, 4000)
      fusion = ActiveModel::Type::Boolean.new.cast(input['fusion'])
      refs = fusion ? [input['character_style'], input['scene_style']] : [input['style']]
      raise RuleError, '普通模式只能使用一个画风' if !fusion && (input['character_style'].present? || input['scene_style'].present? || Array(input['styles']).size > 1)
      raise RuleError, '融合模式需要两个不同画风' if fusion && (refs.any?(&:blank?) || refs.uniq.size != 2)
      refs = refs.reject(&:blank?)
      linked = []
      styles = refs.each_with_index.map do |ref, index|
        asset = Catalog.find(ref)
        kind = asset.is_a?(Entry) ? asset.kind : asset['kind']
        raise RuleError, '画风选择无效' unless kind == 'style'
        linked << { ref: Catalog.ref(asset), kind: 'style', name: asset.is_a?(Entry) ? asset.title : asset['name'], version: asset.is_a?(Entry) ? asset.version : '1.0.0', role: fusion ? %w[character scene][index] : 'style' }
        Catalog.definition(asset, user)
      end
      raise RuleError, '融合模式需要两个不同画风' if fusion && linked.map { |row| row[:ref] }.uniq.size != 2
      ratio = input['ratio'].presence || (fusion ? '3:4' : '1:1')
      raise RuleError, '画幅比例无效' unless ImageService::RATIOS.key?(ratio)
      parts = if fusion
                template = File.read(Handraw::Engine.root.join('content/fusion-prompt.txt'))
                template.sub('{character}', styles[0]).sub('{scene}', styles[1]).sub('{theme}', theme)
              else
                ["请直接生成一张图片，忠实表达主题：#{theme}", "创作类型：#{mode}", styles.first].compact.join("\n\n")
              end
      if input['layout'].present?
        layout = Catalog.find(input['layout'])
        kind = layout.is_a?(Entry) ? layout.kind : layout['kind']
        raise RuleError, '图型选择无效' unless kind == 'layout'
        linked << { ref: Catalog.ref(layout), kind: 'layout', name: layout.is_a?(Entry) ? layout.title : layout['name'], version: layout.is_a?(Entry) ? layout.version : '1.0.0', role: 'layout' }
        parts += "\n\n【图型】：#{Catalog.definition(layout, user)}"
      end
      if input['color'].present?
        color = Catalog.find(input['color'])
        raise RuleError, '配色无效' unless color.is_a?(Hash) && color['kind'] == 'color'
        parts += "\n\n#{Catalog.definition(color, user)}"
      end
      mood = input['mood'].to_s.first(100)
      mood = '治愈' if fusion && mood.blank?
      parts += "\n\n【画幅比例】：#{ratio}。#{mood.present? ? "【情绪】：#{mood}。" : ''}\n不要把参数标签和资源编号画进画面。"
      { prompt: parts, title: theme, ratio: ratio, assets: linked, parameters: input.slice('mode', 'fusion', 'style', 'character_style', 'scene_style', 'layout', 'color', 'ratio', 'mood').merge('mood' => mood) }
    end
  end
end
