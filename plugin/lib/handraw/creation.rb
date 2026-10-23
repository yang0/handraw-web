# frozen_string_literal: true

module Handraw
  module Creation
    MODES = %w[pure graphic-text poster article-cover article-illust photo].freeze
    GRAPHIC_SUFFIX = '【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。 如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，由你先设计画面隐喻（人类和非人类都行）再出图   。    文字参与构图，图文一体】'

    def self.options
      @options ||= JSON.parse(File.read(Handraw::Engine.root.join('content/studio-options.json')))
    end

    def self.plans(user, values)
      input = Publishing.hash(values).stringify_keys
      return [resolve(user, input)] unless ActiveModel::Type::Boolean.new.cast(input['batch'])
      count = Integer(input.fetch('count', 3))
      themes, layouts = input.fetch('themes', []), input.fetch('layouts', [])
      raise RuleError, '每批一至五张，请检查主题和图型列表' unless count.between?(1, 5) && themes.is_a?(Array) && layouts.is_a?(Array) && themes.size <= 5 && layouts.size <= 5
      count.times.map do |i|
        item = input.merge('theme' => themes[i].to_s.presence || input['theme'])
        item['layout'] = layouts[i % layouts.size] if ActiveModel::Type::Boolean.new.cast(input['mix_layouts']) && layouts.any?
        resolve(user, item).merge(batch_position: i + 1, batch_total: count)
      end
    rescue ArgumentError, TypeError
      raise RuleError, '批量数量无效'
    end

    def self.resolve(user, values)
      input = Publishing.hash(values).stringify_keys
      mode = input['mode'].to_s.presence || 'pure'
      raise RuleError, '创作类型无效' unless MODES.include?(mode)
      theme = input['theme'].to_s.strip
      raise RuleError, '请用至少五个字描述主题，文章最多两万字' unless theme.length.between?(5, 20_000)
      if %w[article-illust article-cover].include?(mode) && theme.match?(%r{\A(?:[A-Za-z]:[/\\]|https?://)\S+\z})
        raise RuleError, '在线生图请粘贴文章或上传 TXT／Markdown；路径可复制到 Skill 中使用'
      end
      fusion = ActiveModel::Type::Boolean.new.cast(input['fusion'])
      refs = fusion ? [input['character_style'], input['scene_style']] : [input['style']]
      raise RuleError, '普通模式只能使用一个画风' if !fusion && (input['character_style'].present? || input['scene_style'].present? || Array(input['styles']).size > 1)
      raise RuleError, '融合模式需要两个不同画风' if fusion && (refs.any?(&:blank?) || refs.uniq.size != 2)
      refs = refs.reject(&:blank?)
      linked = []
      references = reference_inputs(user, input)
      styles = refs.each_with_index.map do |ref, index|
        next '写实摄影，真实材质、自然光照与透视关系。' if ref == 'realistic'
        asset = Catalog.find(ref)
        kind = asset.is_a?(Entry) ? asset.kind : asset['kind']
        raise RuleError, '画风选择无效' unless kind == 'style'
        linked << { ref: Catalog.ref(asset), kind: 'style', name: asset.is_a?(Entry) ? asset.title : asset['name'], version: asset.is_a?(Entry) ? asset.version : '1.0.0', role: fusion ? %w[character scene][index] : 'style' }
        if asset.is_a?(Entry)
          Catalog.definition(asset, user)
        else
          policy = options.fetch('styles').fetch(asset['id'])
          references << { 'source'=>'official', 'path'=>policy['reference'], 'role'=>'style', 'name'=>asset['name'] } if policy['reference']
          policy['definition']
        end
      end
      raise RuleError, '融合模式需要两个不同画风' if fusion && refs.map { |ref| ref.to_s.delete_prefix('official:') }.uniq.size != 2
      ratio = input.key?('ratio') ? input['ratio'].to_s.strip : (fusion ? '3:4' : '1:1')
      ImageService.size_for(ratio)
      parts = if fusion
                template = File.read(Handraw::Engine.root.join('content/fusion-prompt.txt'))
                template.sub('{character}', styles[0]).sub('{scene}', styles[1]).sub('{theme}', theme)
              else
                ["请直接生成一张图片，忠实表达主题：#{theme}", "创作类型：#{mode}", styles.first].compact.join("\n\n")
              end
      mode_prompt = {'graphic-text'=>GRAPHIC_SUFFIX, 'poster'=>'设计海报：先设计隐喻再出图，主标题明显，小字少或者没有小字。其他你帮我设计。', 'article-cover'=>'设计文章封面：从文章中提炼核心观点，先设计隐喻再出图，主标题明显，小字少或者没有小字。', 'article-illust'=>'为文章绘制一张正文插图，提炼核心观点与具象隐喻，不把全文排成文字海报。', 'photo'=>'摄影写真，按照拍摄类型与主题安排人物、场景、光线和镜头。'}[mode]
      parts += "\n\n#{mode_prompt}" if mode_prompt
      if input['layout'].present? && !%w[article-cover article-illust].include?(mode)
        layout = Catalog.find(input['layout'])
        kind = layout.is_a?(Entry) ? layout.kind : layout['kind']
        raise RuleError, '图型选择无效' unless kind == 'layout'
        linked << { ref: Catalog.ref(layout), kind: 'layout', name: layout.is_a?(Entry) ? layout.title : layout['name'], version: layout.is_a?(Entry) ? layout.version : '1.0.0', role: 'layout' }
        definition = Catalog.definition(layout, user).split('<!-- en -->').first.delete_prefix('<!-- zh -->').strip
        if !layout.is_a?(Entry) && layout['id'] == 'SC-021'
          variant = Integer(input['layout_variant'].presence || 1)
          raise RuleError, '请选择一种双拼转译类型' unless variant.between?(1, 7)
          direction = ratio.present? && ratio.split(':').map(&:to_f).then { |x| x[0] > x[1] } ? '左右双拼，左侧摄影、右侧手绘' : '上下双拼，上方摄影、下方手绘'
          definition = "自适应双拼照片转译社媒卡。#{direction}。仅采用#{options['sc021_types'][variant-1]}，不混用其他转译类型；手绘侧清除照片环境杂质，保留大量纯净负空间。"
        end
        parts += "\n\n【图型】：#{definition}"
        parts += "\n#{GRAPHIC_SUFFIX}" unless mode == 'graphic-text' || (!layout.is_a?(Entry) && layout['id'].start_with?('EC-'))
      end
      if input['color'].present?
        color = Catalog.find(input['color'])
        raise RuleError, '配色无效' unless color.is_a?(Hash) && color['kind'] == 'color'
        parts += "\n\n#{Catalog.definition(color, user)}"
      end
      mood = input['mood'].to_s.first(100)
      mood = '治愈' if fusion && mood.blank?
      parts += "\n\n#{ratio.present? ? "【画幅比例】：#{ratio}。" : ''}#{mood.present? ? "【情绪】：#{mood}。" : ''}\n不要把参数标签和资源编号画进画面。"
      whitespace = input['whitespace'].to_s.presence || 'normal'
      raise RuleError, '留白无效' unless %w[normal moderate high].include?(whitespace)
      parts += "\n【大量留白】" if whitespace == 'moderate'
      parts += "\n【大量留白，场景只显示必要部分，不要显示全】" if whitespace == 'high'
      tone_ids = input['tones'] || []
      raise RuleError, '影调格式无效' unless tone_ids.is_a?(Array) && tone_ids.size <= 16
      tone_ids.uniq.each do |id|
        tone = options['tones'].find { |item| item['id'] == id }
        raise RuleError, '影调无效' unless tone
        parts += "\n影调：#{tone['name_zh']}，#{tone['desc_zh']}。"
      end
      {'audience'=>'受众','channel'=>'投放渠道','shoot_type'=>'拍摄类型','extra'=>'用户补充要求'}.each do |key,label|
        value = input[key].to_s.first(key == 'extra' ? 4000 : 200)
        parts += "\n#{label}：#{value}" if value.present?
      end
      references.each_with_index { |ref,i| parts += "\n参考图 #{i+1}：#{ref['role']}，#{ref['name']}；仅按此用途参考。" }
      parts += "\n画风示例仅用于线条、笔触、媒介、材质与色彩参考，不复制其中的主体、场景、构图、文字或故事。主题以用户文字为准。" if references.any? { |r| r['role'] == 'style' }
      parts += "\n【请只提取人物的五官特征和姿态，场景轮廓，在画风上严格按 选择的风格重新画，不要在原照片上加质感。】" if references.any? { |r| r['role'] == 'redraw' }
      quality = input['quality'].presence || 'auto'
      raise RuleError, '图片质量无效' unless %w[auto low medium high].include?(quality)
      { prompt: parts, title: theme.first(120), ratio: ratio, assets: linked, references: references, parameters: input.slice('theme', 'mode', 'fusion', 'style', 'character_style', 'scene_style', 'layout', 'color', 'ratio', 'whitespace', 'tones', 'audience', 'channel', 'shoot_type', 'extra', 'layout_variant', 'references', 'asset_refs', 'batch', 'count', 'themes', 'layouts', 'mix_layouts').merge('mood' => mood, 'quality'=>quality) }
    rescue ArgumentError, TypeError
      raise RuleError, '创作选项格式无效'
    end

    def self.reference_inputs(user, input)
      files, assets = input['references'] || [], input['asset_refs'] || []
      raise RuleError, '最多选择六张参考图' unless files.is_a?(Array) && assets.is_a?(Array) && files.size + assets.size <= 6
      rows = files.map do |row|
        item = Publishing.hash(row).stringify_keys
        raise Discourse::InvalidAccess unless user && Access.verified?(user)
        image = PrivateImage.find_by!(public_id: item['id'], user_id: user.id)
        PrivateMedia.path(image)
        role = item['role'].to_s
        raise RuleError, '参考图用途无效' unless %w[characters props scenes redraw style].include?(role)
        { 'source'=>'private', 'id'=>image.public_id, 'role'=>role, 'name'=>item['name'].to_s.first(100) }
      end
      assets.uniq.each do |id|
        asset = options['assets'].find { |item| item['id'] == id }
        raise RuleError, '角色或道具不存在，请上传参考图' unless asset
        rows << { 'source'=>'official', 'path'=>URI(asset['image']).path.delete_prefix('/'), 'role'=>'characters', 'name'=>asset['name'] }
      end
      rows
    end
  end
end
