# frozen_string_literal: true

module Handraw
  module Publishing
    KINDS = %w[work experience style layout].freeze

    def self.hash(value)
      value.respond_to?(:to_unsafe_h) ? value.to_unsafe_h : value.is_a?(Hash) ? value : {}
    end

    def self.content_data(kind, input)
      data = hash(input).stringify_keys.slice('prompt', 'parameters', 'body', 'definition_zh', 'definition_en', 'instructions', 'examples')
      field = { 'work' => 'prompt', 'experience' => 'body', 'style' => 'definition_zh', 'layout' => 'definition_zh' }.fetch(kind)
      raise RuleError, '请填写完整提示词、正文或可复用定义' unless data[field].is_a?(String) && data[field].strip.length.between?(10, 50_000)
      %w[prompt body definition_zh definition_en instructions].each do |key|
        raise RuleError, '内容过长或格式无效' if data.key?(key) && (!data[key].is_a?(String) || data[key].length > 50_000)
      end
      if data.key?('parameters')
        raise RuleError, '生成参数需为 JSON 对象' unless data['parameters'].is_a?(Hash) && JSON.generate(data['parameters']).length <= 8000
      end
      data['examples'] = Array(data['examples']).first(8).map do |example|
        item = hash(example).stringify_keys
        { 'theme' => item['theme'].to_s.first(200), 'image' => safe_image(item['image']) }
      end
      data
    end

    def self.safe_image(value)
      value = value.to_s.strip
      return '' if value.blank?
      uri = URI.parse(value)
      allowed = value.start_with?('/uploads/') && !value.start_with?('//')
      allowed ||= uri.scheme == 'https' && %w[handraw-style.com img.handraw-style.com static.handraw-style.com].include?(uri.host) && !uri.userinfo
      raise RuleError, '图片请使用本站上传或静态资源地址' unless allowed && !value.match?(/[\n\r<>\[\]()]/)
      value
    rescue URI::InvalidURIError
      raise RuleError, '图片地址无效'
    end

    def self.price!(entry, input, initial: false)
      old_price = entry.price
      old_mode = entry.pricing_mode
      if %w[work experience].include?(entry.kind)
        amount = Integer(input['price'] || (initial ? 0 : entry.price))
        cap = SiteSetting.handraw_fixed_price_max
        raise RuleError, "价格须为 0 至 #{cap} 之间的 5 分整数档" unless amount.between?(0, cap) && (amount % 5).zero?
        entry.price = amount
        entry.pricing_mode = amount.zero? ? 'free' : 'fixed'
        entry.paid_opt_in = amount.positive?
      else
        paid = ActiveModel::Type::Boolean.new.cast(input.fetch('paid_opt_in', initial ? false : entry.paid_opt_in))
        entry.paid_opt_in = paid
        entry.pricing_mode = paid ? 'dynamic' : 'free'
        entry.price = paid ? (old_mode == 'dynamic' ? old_price : SiteSetting.handraw_price_initial) : 0
      end
      if !initial && (old_price != entry.price || old_mode != entry.pricing_mode)
        entry.price_revision += 1
        entry.price_reason = entry.pricing_mode == 'fixed' ? '作者调整固定价格' : '作者调整发布方式'
        PriceChange.create!(entry_id: entry.id, old_price: old_price, new_price: entry.price, reason: entry.price_reason)
      end
    rescue ArgumentError, TypeError
      raise RuleError, '价格格式无效'
    end

    def self.create!(user, values, guardian)
      input = hash(values).stringify_keys
      kind = input['kind'].to_s
      raise RuleError, '请选择作品、经验、画风或图型' unless KINDS.include?(kind)
      data = content_data(kind, input['content'])
      cover = safe_image(input['cover_url'])
      raise RuleError, '作品需要一张真实成图' if kind == 'work' && cover.blank?
      summary = input['summary'].to_s.strip
      summary = '作者分享的创作作品，解锁后可查看完整提示词和生成参数。' if summary.blank? && kind == 'work'
      digest = Digest::SHA256.hexdigest([kind, data.except('examples'), cover].to_json)
      raise RuleError, '相同内容已发布，请编辑原投稿' if Entry.exists?(content_digest: digest)
      entry = nil
      Entry.transaction do
        entry = Entry.new(user: user, public_id: SecureRandom.uuid, kind: kind, title: input['title'], summary: summary,
                          cover_url: cover, license: input['license'].presence || '供学习参考；其他用途与转载请联系原作者。',
                          content_digest: digest, pricing_mode: 'free', metadata: { 'content_market' => true, 'examples' => data['examples'] })
        price!(entry, input, initial: true)
        name = { 'work' => '实战作品与爆款', 'experience' => '创作交流' }.fetch(kind, '手绘skill')
        category = Category.find_by(name: name) || Category.find(SiteSetting.uncategorized_category_id)
        raise Discourse::InvalidAccess if category.read_restricted || !guardian.can_create_topic_on_category?(category)
        # Only the public preview reaches Discourse. Secrets never enter raw/cooked/revisions/search/email.
        raw = [summary, "[查看#{kind == 'experience' ? '完整经验' : '内容、图片与使用说明'}](/studio?entry=#{entry.public_id})"].join("\n\n")
        source_topic = input['topic_id'].presence && Topic.find(input['topic_id'])
        if source_topic
          raise Discourse::InvalidAccess unless kind == 'experience' && source_topic.user_id == user.id && source_topic.visible && !source_topic.deleted_at && source_topic.archetype == 'regular' && !source_topic.category.read_restricted
          raise RuleError, '此帖子已收录为经验，请编辑已有经验' if Entry.exists?(topic_id: source_topic.id)
          # Existing public posts stay public. A protected addition must not pretend to hide their history.
          entry.topic = source_topic
          entry.metadata['existing_public_post'] = true
        else
          post = PostCreator.create!(user, title: entry.title, raw: raw, category: category.id)
          entry.topic = post.topic
        end
        entry.save!
        entry.create_content!(data: data)
        Catalog.links!(entry, input['assets'])
        claim_images!(entry, data)
      end
      entry
    end

    def self.update!(entry, user, values)
      raise Discourse::InvalidAccess unless user.id == entry.user_id
      raise RuleError, '旧测试内容请按新格式重新发布' unless entry.market?
      input = hash(values).stringify_keys
      entry.with_lock do
        data = input.key?('content') ? content_data(entry.kind, input['content']) : entry.content.data
        entry.assign_attributes(input.slice('title', 'summary', 'license'))
        entry.cover_url = safe_image(input['cover_url']) if input.key?('cover_url')
        entry.version = input['version'].to_s.first(40) if input['version'].present?
        price!(entry, input)
        if input.key?('content') && entry.resource?
          entry.download_approved = false
          entry.verified = false
          entry.metadata = entry.metadata.merge('examples' => data['examples'])
        end
        entry.content.update!(data: data)
        Catalog.links!(entry, input['assets']) if input.key?('assets')
        claim_images!(entry, data)
        entry.save!
        unless entry.metadata['existing_public_post']
          post = entry.topic.posts.find_by!(post_number: 1)
          raw = [entry.summary, "[查看完整内容与图片](/studio?entry=#{entry.public_id})"].join("\n\n")
          PostRevisor.new(post).revise!(user, raw: raw, title: entry.title)
        end
      end
      entry.reload
    end

    def self.claim_images!(entry, data)
      ids = JSON.generate(data).scan(%r{/studio/api/private-images/([0-9a-f-]{36})}).flatten.uniq
      ids.each do |id|
        image = PrivateImage.find_by!(public_id: id)
        raise Discourse::InvalidAccess unless image.user_id == entry.user_id && (image.entry_id.nil? || image.entry_id == entry.id)
        image.update!(entry_id: entry.id)
      end
    end
  end
end
