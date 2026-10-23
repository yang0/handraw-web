# frozen_string_literal: true

module Handraw
  class PortalController < ::ApplicationController
    requires_plugin Handraw::PLUGIN_NAME
    skip_before_action :check_xhr
    # This allowlisted action serves public static JavaScript to same-origin script tags.
    skip_after_action :verify_same_origin_request, only: :asset
    before_action :require_enabled
    before_action :ensure_logged_in, except: %i[index asset boot feed show creator assets asset_show asset_content related content private_image topic_experience resolve_creation]
    before_action :ensure_participant, only: %i[create update upload_bundle]
    before_action :ensure_verified, only: %i[welcome unlock generation_create generation_retry generation_cancel private_image_upload]
    before_action :ensure_reviewer, only: %i[review_queue review refund freeze_wallet review_download curate_experience uncurate_experience]

    rescue_from Handraw::RuleError do |error|
      render json: { errors: [error.message] }, status: :unprocessable_entity
    end

    rescue_from ActiveRecord::RecordInvalid do |error|
      render json: { errors: error.record.errors.full_messages }, status: :unprocessable_entity
    end
    rescue_from ActiveRecord::RecordNotSaved do |error|
      render json: { errors: [error.message] }, status: :unprocessable_entity
    end

    def index
      nonce = ContentSecurityPolicy.nonce_placeholder(response.headers, request_env: request.env)
      page = File.read(Handraw::Engine.root.join('public', 'index.html'))
      view = params[:creator].present? ? 'creator' : (params[:view].to_s.presence || 'home')
      active = case view
               when 'resources', 'explore' then 'explore'
               when 'works', 'experience', 'community', 'creator' then 'community'
               when 'create', 'learn' then view
               end
      page = page.sub('<!-- handraw-navigation -->', Handraw::Navigation.render(active: active))
      page = page.sub('id="hero"', 'id="hero" hidden') unless view == 'home'
      page = page.sub('<script src="/studio/assets/portal.js"', "<script nonce=\"#{nonce}\" src=\"/studio/assets/portal.js\"")
      page = page.sub('<script src="/studio/assets/image-loader.js"', "<script nonce=\"#{nonce}\" src=\"/studio/assets/image-loader.js\"")
      page = page.sub('<script src="/studio/assets/discover.js"', "<script nonce=\"#{nonce}\" src=\"/studio/assets/discover.js\"")
      page = page.sub('<script src="/studio/assets/market.js"', "<script nonce=\"#{nonce}\" src=\"/studio/assets/market.js\"")
      %w[studio.js composer-core.js].each do |name|
        page = page.sub("<script src=\"/studio/assets/#{name}\"", "<script nonce=\"#{nonce}\" src=\"/studio/assets/#{name}\"")
      end
      if release_version.match?(/\A[0-9a-f]{40}\z/)
        page = page.gsub('/studio/assets/', "https://static.handraw-style.com/handraw-web/releases/#{release_version}/assets/")
      end
      render body: page, content_type: 'text/html', layout: false
    end

    def asset
      name = params[:name]
      raise Discourse::NotFound if %w[portal.js market.js forum-experience.js portal.css market.css navigation.css image-loader.js discover.js composer-bridge.js composer-core.js studio.js studio.css studio-options.json composer.html catalog.json].exclude?(name)

      path = Handraw::Engine.root.join(%w[catalog.json studio-options.json].include?(name) ? 'content' : 'public', name)
      send_file path, disposition: 'inline',
                                                           type: name.end_with?('.json') ? 'application/json' : name.end_with?('.js') ? 'text/javascript' : name.end_with?('.html') ? 'text/html' : 'text/css'
    end

    def boot
      render json: {
        user: current_user ? { id: current_user.id, username: current_user.username, name: current_user.name } : nil,
        participant: Access.participant?(current_user),
        reviewer: Access.reviewer?(current_user),
        pilot: !SiteSetting.handraw_public_submissions,
        official: { styles: 'https://static.handraw-style.com/gallery/index.html',
                    layouts: 'https://static.handraw-style.com/gallery/layouts.html' },
        rules: {
          welcome: SiteSetting.handraw_welcome_credits,
          settlement_days: SiteSetting.handraw_settlement_days,
          author_percent: SiteSetting.handraw_author_share_percent,
          initial_price: SiteSetting.handraw_price_initial.clamp(SiteSetting.handraw_price_min,
                                                               [SiteSetting.handraw_price_max, SiteSetting.handraw_price_min].max),
          min_price: SiteSetting.handraw_price_min,
          max_price: [SiteSetting.handraw_price_max, SiteSetting.handraw_price_min].max,
          price_days: SiteSetting.handraw_price_window_days
        },
        categories: Category.secured(guardian).where(read_restricted: false).order(:position).pluck(:id, :name),
        editorial: Editorial.payload,
        generation: { enabled: ImageService.enabled?, available: ImageService.enabled? && Access.verified?(current_user),
                      daily_limit: SiteSetting.handraw_generation_daily_limit },
        fixed_price_max: SiteSetting.handraw_fixed_price_max,
        min_title_length: [5, SiteSetting.min_topic_title_length].max,
        release: release_version
      }
    end

    def generation_create
      RateLimiter.new(current_user, 'handraw-generation-submit', 10, 1.minute).performed!
      plans = Creation.plans(current_user, params.require(:creation))
      tasks = ImageService.submit_batch(current_user, client_id: params[:client_id], plans: plans)
      render json: tasks.first.merge(tasks: tasks)
    end

    def generation_index
      RateLimiter.new(current_user, 'handraw-generation-poll', 10, 1.minute).performed!
      response.headers['Cache-Control'] = 'private, no-store'
      render json: ImageService.list(current_user, refresh: params[:refresh] == '1')
    end

    def generation_retry
      RateLimiter.new(current_user, 'handraw-generation-confirm', 5, 1.minute).performed!
      render json: ImageService.dispatch(current_user, params[:id])
    end

    def generation_cancel
      ImageService.cancel_waiting(current_user, params[:batch_id].to_s)
      head :no_content
    end

    def generation_image
      bytes, media_type = ImageService.image(current_user, params[:id], params[:index])
      response.headers['Cache-Control'] = 'private, no-store'
      send_data bytes, type: media_type, disposition: 'inline'
    end

    def generation_content
      task = ImageService.store(current_user)['tasks'].find { |item| item['id'] == params[:id] }
      raise Discourse::NotFound unless task
      response.headers['Cache-Control'] = 'private, no-store'
      render json: { prompt: task['prompt'], creation: task['creation'] }
    end

    def resolve_creation
      response.headers['Cache-Control'] = 'private, no-store'
      plans = Creation.plans(current_user, params.require(:creation))
      render json: plans.first.merge(plans: plans)
    end

    def assets
      kind = params[:kind].to_s.presence || 'style'
      raise RuleError, '请选择画风或图型' unless %w[style layout].include?(kind)
      source = params[:source].to_s
      items = source == 'community' ? [] : Catalog.official.select { |item| item['kind'] == kind }.map { |item| Catalog.payload(item, current_user) }
      unless source == 'official'
        community = Feed.call(kind: kind, page: params[:page], sort: params[:sort], search: params[:q]).map { |item| Catalog.payload(item, current_user) }
        if source == 'community'
          items = community
        else
          # Give community assets a place near the beginning, without displacing the official library.
          items = items.each_slice(3).flat_map { |group| group + (community.empty? ? [] : [community.shift]) } + community
        end
      end
      if params[:q].present?
        q = params[:q].to_s.downcase.delete_prefix('#').first(100)
        items = items.select do |item|
          if kind == 'style' && q.match?(/\A\d{1,3}\z/) && item['source'] == 'official'
            item['legacy'].present? && item['legacy'].to_i == q.to_i
          else
            [item[:title], item[:summary], item['name'], item['id'], item['legacy'], item['description']].join(' ').downcase.include?(q)
          end
        end
      end
      render json: { assets: items }
    end

    def asset_show
      asset = Catalog.find(params[:ref])
      payload = Catalog.payload(asset, current_user)
      payload['collected'] = current_user && AssetCollection.exists?(user_id: current_user.id, asset_ref: Catalog.ref(asset)) if asset.is_a?(Hash)
      render json: payload
    end

    def topic_experience
      topic = Topic.find(params[:topic_id])
      guardian.ensure_can_see!(topic)
      record = Entry.visible.find_by(topic_id: params[:topic_id], kind: 'experience')
      render json: { entry: record&.public_payload(current_user) }
    end

    def curate_experience
      RateLimiter.new(current_user, 'handraw-curate-experience', 30, 1.minute).performed!
      record = ForumCuration.mark!(Topic.find(params[:topic_id]), current_user, guardian, assets: params[:assets])
      render json: { entry: record.public_payload(current_user) }
    end

    def uncurate_experience
      ForumCuration.unmark!(Topic.find(params[:topic_id]), current_user, guardian)
      head :no_content
    end

    def asset_content
      asset = Catalog.find(params[:ref])
      response.headers['Cache-Control'] = 'private, no-store'
      if asset.is_a?(Entry)
        params[:id] = asset.public_id
        return content
      end
      resource = { id: Catalog.ref(asset), kind: asset['kind'], name: asset['name'],
                   prompt_zh: Catalog.definition(asset, current_user), prompt_en: Catalog.definition(asset, current_user),
                   license: '沿用官方 Skill 的使用说明', version: '1.0.0', author: { name: '手绘风官方' },
                   source: "/studio?view=explore&asset=#{Catalog.ref(asset)}" }
      render json: { resource: resource, sha256: Digest::SHA256.hexdigest(JSON.generate(resource)) }
    end

    def related
      asset = Catalog.find(params[:ref])
      ids = AssetLink.where(asset_ref: Catalog.ref(asset)).select(:entry_id)
      records = Entry.visible.for_listing.where(id: ids).includes(:user).order(featured: :desc, created_at: :desc).limit(40)
      render json: { works: records.where(kind: 'work').map { |e| e.public_payload(current_user) },
                     experiences: records.where(kind: 'experience').map { |e| e.public_payload(current_user) } }
    end

    def asset_collect
      raise Discourse::InvalidAccess unless Access.verified?(current_user)
      asset = Catalog.find(params[:ref])
      if asset.is_a?(Entry)
        raise RuleError, '自己的资源已在我的创作中' if asset.user_id == current_user.id
        Collection.create_or_find_by!(entry_id: asset.id, user_id: current_user.id)
      else
        AssetCollection.create_or_find_by!(user_id: current_user.id, asset_ref: Catalog.ref(asset))
      end
      render json: { collected: true }
    end

    def asset_uncollect
      asset = Catalog.find(params[:ref])
      if asset.is_a?(Entry)
        Collection.where(user_id: current_user.id, entry_id: asset.id).destroy_all
      else
        AssetCollection.where(user_id: current_user.id, asset_ref: Catalog.ref(asset)).destroy_all
      end
      head :no_content
    end

    def content
      record = entry
      raise Discourse::InvalidAccess unless record.content_readable?(current_user)
      response.headers['Cache-Control'] = 'private, no-store'
      response.headers['Vary'] = 'Cookie'
      data = record.content.data.deep_dup
      if Access.verified?(current_user) && record.user_id != current_user.id
        Event.create_or_find_by!(entry_id: record.id, user_id: current_user.id, kind: 'access', day: Date.current) do |event|
          event.qualified = Access.qualified?(current_user)
        end
      end
      data['body_html'] = PrettyText.cook(data['body']) if data['body'].present?
      payload = { id: record.public_id, kind: record.kind, version: record.version, content: data }
      if record.resource?
        resource = { id: "community:#{record.public_id}", kind: record.kind, name: record.title,
                     prompt_zh: data['definition_zh'], prompt_en: data['definition_en'].presence || data['definition_zh'],
                     license: record.license, version: record.version, author: record.public_payload[:author],
                     source: "/studio?entry=#{record.public_id}" }
        payload[:resource] = resource
        payload[:sha256] = Digest::SHA256.hexdigest(JSON.generate(resource))
      end
      render json: payload
    end

    def update
      record = Publishing.update!(entry, current_user, params.require(:entry))
      render json: record.public_payload(current_user)
    end

    def private_image_upload
      RateLimiter.new(current_user, 'handraw-private-image-upload', 30, 1.day).performed!
      image = PrivateMedia.save!(current_user, params.require(:file))
      render json: { url: "/studio/api/private-images/#{image.public_id}" }, status: :created
    end

    def private_image
      image = PrivateImage.find_by!(public_id: params[:image_id])
      allowed = image.user_id == current_user&.id
      if image.entry && !allowed
        if Access.reviewer?(current_user)
          Audit.create!(user_id: current_user.id, entry_id: image.entry_id,
                        action: 'inspect_private_image', reason: '审核已投稿的受保护正文配图')
          allowed = true
        else
          Entry.visible.find(image.entry_id)
          allowed = image.entry.content_readable?(current_user)
        end
      end
      raise Discourse::InvalidAccess unless allowed
      response.headers['Cache-Control'] = 'private, no-store'
      response.headers['X-Content-Type-Options'] = 'nosniff'
      send_file PrivateMedia.path(image), type: image.media_type, disposition: 'inline'
    end

    def feed
      entries = Feed.call(kind: params[:kind], page: params[:page], search: params[:q], sort: params[:sort])
      topics = params[:kind] == 'work' ? [] : TopicQuery.new(current_user, per_page: 6).list_latest.topics
      render json: {
        entries: entries.map { |entry| entry.public_payload(current_user) },
        discussions: topics.map do |topic|
          { title: topic.title, url: "/t/#{topic.id}", posts_count: topic.posts_count }
        end
      }
    end

    def creator
      user = User.find_by!(username_lower: params[:username].to_s.downcase)
      scope = Entry.visible.for_listing.where(user_id: user.id)
      entries = scope.includes(:user).order(created_at: :desc).limit(100)
      render json: {
        author: { username: user.username, name: user.name, profile_url: "/u/#{user.username}" },
        featured_count: entries.count(&:featured),
        verified_count: entries.count(&:verified),
        contributions: %w[work style layout experience].to_h do |kind|
          group = scope.where(kind: kind)
          useful = Event.where(entry_id: group.select(:id), kind: 'useful', qualified: true).distinct.count(:user_id)
          reused = Event.where(entry_id: group.select(:id), kind: 'reuse', qualified: true).distinct.count(:user_id)
          featured = group.where(featured: true).count
          verified = group.where(verified: true).count
          honor = { 'work' => '精选创作者', 'style' => '画风贡献者', 'layout' => '图型贡献者', 'experience' => '经验分享者' }[kind]
          earned = featured.positive? || (%w[style layout].include?(kind) && verified.positive?) || (kind == 'experience' && useful >= 3)
          [kind, { published: group.count, featured: featured, verified: verified, useful_users: useful, reuse_users: reused, honor: earned ? honor : nil }]
        end,
        entries: entries.map { |entry| entry.public_payload(current_user) }
      }
    end

    def show
      render json: entry.public_payload(current_user)
    end

    def create
      RateLimiter.new(current_user, 'handraw-post', 10, 1.day).performed!
      if params.dig(:entry, :content).present?
        record = Publishing.create!(current_user, params.require(:entry), guardian)
        return render json: record.public_payload(current_user), status: :created
      end
      raise RuleError, '请使用新版投稿表单，填写完整内容'
    end

    def library
      collected_ids = Collection.where(user_id: current_user.id).pluck(:entry_id)
      unlocked_ids = Unlock.active.where(user_id: current_user.id).pluck(:entry_id)
      ids = (collected_ids + unlocked_ids).uniq
      render json: {
        owned: Entry.for_listing.where(user_id: current_user.id).includes(:user).order(created_at: :desc).limit(200)
                    .map { |record| record.public_payload(current_user).merge(status: record.status,
                      content_url: record.market? ? "/studio/api/entries/#{record.public_id}/content" : nil) },
        collected: Entry.visible.for_listing.where(id: ids).includes(:user).order(created_at: :desc).limit(500)
                        .map do |record|
          record.public_payload(current_user).merge(
            sha256: record.bundle_sha256,
            download_url: record.market? ? nil : record.accessible_to?(current_user) ? "/studio/api/entries/#{record.public_id}/download" : nil,
            content_url: record.market? && record.content_readable?(current_user) ? "/studio/api/entries/#{record.public_id}/content" : nil
          )
        end,
        official: AssetCollection.where(user_id: current_user.id).filter_map do |collection|
          asset = Catalog.find(collection.asset_ref) rescue nil
          Catalog.payload(asset, current_user).merge('collected' => true) if asset
        end
      }
    end

    def collect
      raise RuleError, '自己的资源已在我的创作中' if entry.user_id == current_user.id
      raise Discourse::InvalidAccess unless Access.verified?(current_user)

      Collection.create_or_find_by!(entry_id: entry.id, user_id: current_user.id)
      render json: entry.public_payload(current_user)
    end

    def uncollect
      Collection.where(entry_id: entry.id, user_id: current_user.id).destroy_all
      head :no_content
    end

    def event
      RateLimiter.new(current_user, 'handraw-event', 240, 1.minute).performed!
      kind = params.require(:kind).to_s
      raise RuleError, '未知反馈类型' if %w[impression detail useful not_useful].exclude?(kind)
      raise Discourse::InvalidAccess unless Access.verified?(current_user) && entry.user_id != current_user.id
      if kind == 'impression' && (params[:visible_ms].to_i < 2000 || params[:visible_ratio].to_f < 0.5)
        return head :no_content
      end

      if %w[useful not_useful].include?(kind)
        raise RuleError, '请先查看内容再评价' unless entry.events.exists?(user_id: current_user.id, kind: 'detail')
        raise RuleError, '请先阅读或使用完整内容再评价' if entry.market? && !entry.events.exists?(user_id: current_user.id, kind: 'access')
        if entry.paid_opt_in && !entry.accessible_to?(current_user)
          raise RuleError, '请解锁并使用内容后再评价'
        end

        entry.with_lock do
          Event.where(entry_id: entry.id, user_id: current_user.id, kind: %w[useful not_useful]).destroy_all
          Event.create!(entry_id: entry.id, user_id: current_user.id, kind: kind,
                        day: Date.current, qualified: Access.qualified?(current_user))
        end
        Economy.contribution!(entry) if kind == 'useful'
      else
        Event.create_or_find_by!(entry_id: entry.id, user_id: current_user.id, kind: kind,
                                 day: Date.current) do |record|
          record.qualified = Access.qualified?(current_user)
        end
      end
      head :no_content
    end

    def impressions
      raise Discourse::InvalidAccess unless Access.verified?(current_user)

      RateLimiter.new(current_user, 'handraw-impressions', 60, 1.minute).performed!
      samples = Array(params[:entries]).first(20).select do |sample|
        sample.is_a?(ActionController::Parameters) && sample[:visible_ms].to_i >= 2000 && sample[:visible_ratio].to_f >= 0.5
      end
      ids = samples.map { |sample| sample[:id].to_s }.uniq
      Entry.visible.where(public_id: ids).where.not(user_id: current_user.id).find_each do |record|
        Event.create_or_find_by!(entry_id: record.id, user_id: current_user.id, kind: 'impression', day: Date.current) do |event|
          event.qualified = Access.qualified?(current_user)
        end
      end
      head :no_content
    end

    def wallet
      account = Wallet.for_user(current_user.id)
      render json: {
        balance: account.balance,
        frozen: account.locked,
        welcome_claimed: Ledger.exists?(user_id: current_user.id, event_key: 'welcome'),
        pending: Unlock.active.where(author_id: current_user.id, settled_at: nil).sum(:author_amount),
        entries: Ledger.where(user_id: current_user.id).order(id: :desc).limit(100)
                       .as_json(only: %i[amount reason created_at])
      }
    end

    def welcome
      Economy.welcome!(current_user, [true, 'true'].include?(params[:accepted]))
      wallet
    end

    def upload_bundle
      raise Discourse::InvalidAccess unless entry.user_id == current_user.id

      BundleStore.save!(entry, params.require(:file))
      render json: entry.reload.public_payload(current_user)
    end

    def unlock
      Economy.unlock!(entry, current_user, Integer(params.require(:price)), Integer(params.require(:price_revision)))
      render json: entry.reload.public_payload(current_user)
    rescue ArgumentError
      raise RuleError, '价格参数无效'
    end

    def download
      raise Discourse::InvalidAccess unless entry.accessible_to?(current_user)
      raise RuleError, '资源已暂停下载，请联系版主' unless entry.download_approved

      response.headers['Cache-Control'] = 'private, no-store'
      response.headers['X-Content-Type-Options'] = 'nosniff'
      response.headers['X-Resource-SHA256'] = entry.bundle_sha256
      send_file BundleStore.path(entry), filename: entry.bundle_filename, type: 'application/zip',
                                         disposition: 'attachment'
    end

    def report
      reason = params.require(:reason).to_s.strip
      raise RuleError, '请写明问题（至少五个字）' unless reason.length.between?(5, 2000)
      raise RuleError, '请在自己的投稿中补充说明或提交申诉' if entry.user_id == current_user.id

      record = Report.find_or_initialize_by(entry_id: entry.id, user_id: current_user.id)
      record.update!(reason: reason, status: 'open')
      head :no_content
    end

    def review_queue
      records = Entry.includes(:user).order(created_at: :desc).limit(200)
      render json: {
        entries: records.map do |record|
          record.public_payload(current_user).merge(
            internal_id: record.id, status: record.status, has_bundle: record.bundled?, paid_opt_in: record.paid_opt_in,
            download_approved: record.download_approved, examples: record.metadata['examples']
          )
        end,
        reports: Report.where(status: 'open').order(created_at: :asc).limit(100)
                       .as_json(only: %i[id entry_id user_id reason status]),
        unlocks: Unlock.where(refunded_at: nil).order(id: :desc).limit(100)
                       .as_json(only: %i[id entry_id user_id author_id amount author_amount settled_at held]),
        audits: Audit.order(id: :desc).limit(100).as_json(only: %i[user_id entry_id action reason details created_at])
      }
    end

    def review
      record = Entry.find_by!(public_id: params[:id])
      raise RuleError, '不能审核自己的投稿' if record.user_id == current_user.id

      reason = params.require(:reason).to_s.strip
      raise RuleError, '审核理由至少五个字' unless reason.length.between?(5, 2000)

      action = params.require(:action_name)
      record.with_lock do
        case action
        when 'feature'
          record.featured = true
          Economy.editorial_award!(record, SiteSetting.handraw_featured_credits)
        when 'unfeature'
          record.featured = false
        when 'verify', 'approve_download'
          raise RuleError, '仅画风和图型需要复用审核' unless record.resource?
          if record.market?
            raise RuleError, '请先补全可复用定义' unless record.content.present?
            examples = record.metadata['examples']
            minimum = record.kind == 'style' ? 3 : 2
            valid = Array(examples).select { |sample| sample.is_a?(Hash) && sample['theme'].present? && sample['image'].present? }
            raise RuleError, "需要 #{minimum} 个不同主题及图片的复用示例" unless valid.map { |s| s['theme'].strip }.uniq.size >= minimum && valid.map { |s| s['image'] }.uniq.size >= minimum
          else
            raise RuleError, '请先补全画风或图型定义' unless record.bundled?
            BundleStore.path(record)
          end
          record.verified = true
          record.download_approved = true
          reusable_free = !record.paid_opt_in && %w[style layout].include?(record.kind)
          Economy.editorial_award!(record, SiteSetting.handraw_verified_resource_credits) if reusable_free
        when 'pause', 'hide'
          record.status = action == 'hide' ? 'hidden' : 'paused'
          record.download_approved = false
          record.featured = false
        when 'restore'
          record.status = 'published'
        when 'confirm_report', 'dismiss_report'
          report = Report.find(params.require(:report_id))
          raise Discourse::InvalidAccess unless report.entry_id == record.id && report.user_id != current_user.id

          report.update!(status: action == 'confirm_report' ? 'confirmed' : 'dismissed')
        else
          raise RuleError, '未知审核操作'
        end
        record.save!
        Audit.create!(user_id: current_user.id, entry_id: record.id, action: action, reason: reason)
      end
      render json: record.public_payload(current_user)
    end

    def review_download
      record = Entry.find_by!(public_id: params[:id])
      raise RuleError, '不能审核自己的投稿' if record.user_id == current_user.id

      if record.market?
        Audit.create!(user_id: current_user.id, entry_id: record.id, action: 'inspect_content', reason: '检查定义、示例与授权')
        response.headers['Cache-Control'] = 'private, no-store'
        return render json: { content: record.content&.data, entry: record.public_payload(current_user) }
      end

      Audit.create!(user_id: current_user.id, entry_id: record.id, action: 'inspect_bundle', reason: '下载资源包进行复用与授权审核')
      response.headers['Cache-Control'] = 'private, no-store'
      send_file BundleStore.path(record), filename: record.bundle_filename, type: 'application/zip',
                                          disposition: 'attachment'
    end

    def appeal
      record = Entry.find_by!(public_id: params[:id])
      raise Discourse::InvalidAccess unless record.user_id == current_user.id

      reason = params.require(:reason).to_s.strip
      raise RuleError, '申诉至少五个字' unless reason.length.between?(5, 2000)

      RateLimiter.new(current_user, 'handraw-appeal', 3, 1.day).performed!
      Report.find_or_initialize_by(entry_id: record.id, user_id: current_user.id).update!(reason: reason,
                                                                                          status: 'open')
      head :no_content
    end

    def refund
      record = Unlock.find(params[:id])
      reason = params.require(:reason).to_s.strip
      raise RuleError, '请提供退款理由' unless reason.length.between?(5, 2000)

      record.refund!(current_user, reason)
      head :no_content
    end

    def freeze_wallet
      target = User.find(params[:id])
      account = Wallet.for_user(target.id)
      raise RuleError, '不能修改自己的冻结状态' if account.user_id == current_user.id

      reason = params.require(:reason).to_s.strip
      raise RuleError, '请提供处理理由' unless reason.length.between?(5, 2000)

      frozen = ActiveModel::Type::Boolean.new.cast(params.require(:frozen))
      raise RuleError, '请先补足追回的积分' if !frozen && account.balance.negative?

      account.with_lock do
        account.update!(locked: frozen)
        Audit.create!(user_id: current_user.id, action: 'freeze_wallet', reason: reason,
                      details: { account_user_id: account.user_id, frozen: frozen })
      end
      head :no_content
    end

    private

    def release_version
      revision = Handraw::Engine.root.join('REVISION')
      ENV['HANDRAW_RELEASE'].presence || (revision.file? ? revision.read.strip : 'development')
    end

    def require_enabled
      raise Discourse::NotFound unless SiteSetting.handraw_enabled
    end

    def ensure_participant
      raise Discourse::InvalidAccess unless Access.participant?(current_user)
    end

    def ensure_verified
      raise Discourse::InvalidAccess unless Access.verified?(current_user)
    end

    def ensure_reviewer
      raise Discourse::InvalidAccess unless Access.reviewer?(current_user)
    end

    def entry
      @entry ||= Entry.find_by!(public_id: params[:id]).tap do |record|
        Entry.visible.find(record.id) unless current_user&.id == record.user_id
        guardian.ensure_can_see!(record.topic)
      end
    end

    def safe_cover(value)
      value = value.to_s.strip
      return '' if value.blank?

      uri = URI.parse(value)
      allowed_hosts = ['handraw-style.com', 'img.handraw-style.com', 'static.handraw-style.com']
      allowed = value.start_with?('/uploads/') && !value.start_with?('//')
      allowed ||= uri.scheme == 'https' && allowed_hosts.include?(uri.host) && !uri.userinfo
      raise RuleError, '封面请使用本站上传图片或本站静态资源地址' unless allowed && !value.match?(/[\n\r<>\[\]()]/)

      value
    rescue URI::InvalidURIError
      raise RuleError, '封面地址无效'
    end
  end
end
