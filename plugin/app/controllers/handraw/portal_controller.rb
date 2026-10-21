# frozen_string_literal: true

module Handraw
  class PortalController < ::ApplicationController
    requires_plugin Handraw::PLUGIN_NAME
    skip_before_action :check_xhr
    # This allowlisted action serves public static JavaScript to same-origin script tags.
    skip_after_action :verify_same_origin_request, only: :asset
    before_action :require_enabled
    before_action :ensure_logged_in, except: %i[index asset boot feed show creator]
    before_action :ensure_participant, only: %i[create upload_bundle welcome unlock]
    before_action :ensure_reviewer, only: %i[review_queue review refund freeze_wallet review_download]

    rescue_from Handraw::RuleError do |error|
      render json: { errors: [error.message] }, status: :unprocessable_entity
    end

    rescue_from ActiveRecord::RecordInvalid do |error|
      render json: { errors: error.record.errors.full_messages }, status: :unprocessable_entity
    end

    def index
      nonce = ContentSecurityPolicy.nonce_placeholder(response.headers, request_env: request.env)
      page = File.read(Handraw::Engine.root.join('public', 'index.html'))
      page = page.sub('<script src="/studio/assets/portal.js"', "<script nonce=\"#{nonce}\" src=\"/studio/assets/portal.js\"")
      render body: page, content_type: 'text/html', layout: false
    end

    def asset
      name = params[:name]
      raise Discourse::NotFound if %w[portal.js portal.css].exclude?(name)

      send_file Handraw::Engine.root.join('public', name), disposition: 'inline',
                                                           type: name.end_with?('.js') ? 'text/javascript' : 'text/css'
    end

    def boot
      render json: {
        user: current_user ? { id: current_user.id, username: current_user.username, name: current_user.name } : nil,
        participant: Access.participant?(current_user),
        reviewer: Access.reviewer?(current_user),
        pilot: !SiteSetting.handraw_public_submissions,
        official: { styles: '/gallery/index.html', layouts: '/gallery/layouts.html' },
        categories: Category.secured(guardian).where(read_restricted: false).order(:position).pluck(:id, :name),
        release: ENV.fetch('HANDRAW_RELEASE', 'development')
      }
    end

    def feed
      entries = Feed.call(kind: params[:kind], page: params[:page], search: params[:q])
      topics = TopicQuery.new(current_user, per_page: 6).list_latest.topics
      render json: {
        entries: entries.map { |entry| entry.public_payload(current_user) },
        discussions: topics.map do |topic|
          { title: topic.title, url: "/t/#{topic.id}", posts_count: topic.posts_count }
        end
      }
    end

    def creator
      user = User.find_by!(username_lower: params[:username].to_s.downcase)
      entries = Entry.visible.where(user_id: user.id).includes(:user).order(created_at: :desc).limit(100)
      render json: {
        author: { username: user.username, name: user.name, profile_url: "/u/#{user.username}" },
        featured_count: entries.count(&:featured),
        verified_count: entries.count(&:verified),
        entries: entries.map { |entry| entry.public_payload(current_user) }
      }
    end

    def show
      render json: entry.public_payload(current_user)
    end

    def create
      RateLimiter.new(current_user, 'handraw-post', 10, 1.day).performed!
      data = params.require(:entry).permit(:kind, :title, :summary, :cover_url, :license, :category_id, :paid_opt_in)
      category = Category.find(data[:category_id])
      raise Discourse::InvalidAccess if category.read_restricted || !guardian.can_create_topic_on_category?(category)

      cover = safe_cover(data[:cover_url])
      digest = Digest::SHA256.hexdigest([data[:kind], data[:summary].to_s.strip, cover].join("\n"))
      raise RuleError, '相同内容已发布，请更新原投稿' if Entry.exists?(content_digest: digest)

      record = nil
      Entry.transaction do
        record = Entry.new(
          user_id: current_user.id,
          public_id: SecureRandom.uuid,
          kind: data[:kind],
          title: data[:title],
          summary: data[:summary],
          cover_url: cover,
          license: data[:license],
          paid_opt_in: ActiveModel::Type::Boolean.new.cast(data[:paid_opt_in]),
          content_digest: digest
        )
        # Validate before creating the discussion so malformed drafts have no external effects.
        record.valid?
        errors = record.errors.reject { |error| error.attribute == :topic }
        raise RuleError, errors.map(&:full_message).join('，') if errors.any?

        post = PostCreator.create!(current_user, title: record.title,
                                                 raw: [cover.present? ? "![作品](#{cover})" : nil, record.summary,
                                                       "授权说明：#{record.license}"].compact.join("\n\n"), category: category.id)
        record.topic = post.topic
        record.save!
      end
      render json: record.public_payload(current_user), status: :created
    end

    def library
      collected_ids = Collection.where(user_id: current_user.id).pluck(:entry_id)
      unlocked_ids = Unlock.active.where(user_id: current_user.id).pluck(:entry_id)
      ids = (collected_ids + unlocked_ids).uniq
      render json: {
        owned: Entry.where(user_id: current_user.id).includes(:user).order(created_at: :desc).limit(200)
                    .map { |record| record.public_payload(current_user).merge(status: record.status) },
        collected: Entry.visible.where(id: ids).includes(:user).order(created_at: :desc).limit(500)
                        .map do |record|
          record.public_payload(current_user).merge(
            sha256: record.bundle_sha256,
            download_url: record.accessible_to?(current_user) ? "/studio/api/entries/#{record.public_id}/download" : nil
          )
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
        if %w[style layout package].include?(entry.kind) && !entry.accessible_to?(current_user)
          raise RuleError, '请获取并使用资源后再评价'
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
          raise RuleError, '请先上传资源包' unless record.bundled?

          BundleStore.path(record)
          if %w[style layout].include?(record.kind)
            examples = record.metadata['examples']
            raise RuleError, '需要三个不同主题的复用示例' unless examples.is_a?(Array) && examples.size >= 3
          end
          record.verified = true
          record.download_approved = true
          record.featured = true
          award = record.paid_opt_in ? SiteSetting.handraw_featured_credits : SiteSetting.handraw_verified_resource_credits
          Economy.editorial_award!(record, award)
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
      account = Wallet.find_by!(user_id: params[:id])
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

    def require_enabled
      raise Discourse::NotFound unless SiteSetting.handraw_enabled
    end

    def ensure_participant
      raise Discourse::InvalidAccess unless Access.participant?(current_user)
    end

    def ensure_reviewer
      raise Discourse::InvalidAccess unless Access.reviewer?(current_user)
    end

    def entry
      @entry ||= Entry.visible.find_by!(public_id: params[:id]).tap { |record| guardian.ensure_can_see!(record.topic) }
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
