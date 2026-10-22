# frozen_string_literal: true

require 'net/http'
require 'uri'

module Handraw
  module ImageService
    NAMESPACE = 'handraw-generations'
    ACTIVE = %w[queued running].freeze
    RATIOS = { '1:1' => '1024x1024', '3:4' => '1152x1536', '4:3' => '1536x1152',
               '9:16' => '864x1536', '16:9' => '1536x864' }.freeze

    def self.config
      return {} unless Rails.env.production? || ENV.key?('HANDRAW_IMAGE_CONFIG')

      path = ENV.fetch('HANDRAW_IMAGE_CONFIG', '/home/yang0/handraw-data/image-service.json')
      value = File.file?(path) ? JSON.parse(File.read(path)) : {}
      value.is_a?(Hash) ? value : {}
    rescue JSON::ParserError, SystemCallError
      {}
    end

    def self.enabled?
      config['key'].is_a?(String) && config['key'].present?
    end

    def self.request(path, payload: nil)
      settings = config
      raise RuleError, '在线生图暂未开放' if settings['key'].blank?

      base = URI(settings.fetch('url', 'http://127.0.0.1:8000'))
      raise RuleError, '生图服务配置无效' unless base.scheme == 'http' && base.host == '127.0.0.1' && base.port == 8000

      uri = base + path
      operation = payload ? Net::HTTP::Post.new(uri) : Net::HTTP::Get.new(uri)
      operation['Authorization'] = "Bearer #{settings['key']}"
      operation['Content-Type'] = 'application/json'
      operation['Host'] = 'chatgpt2api.handraw-style.com'
      operation.body = JSON.generate(payload) if payload
      response = Net::HTTP.start(uri.host, uri.port, nil, open_timeout: 3, read_timeout: 15) { |http| http.request(operation) }
      raise RuleError, '生图服务繁忙，请稍后确认任务' unless response.is_a?(Net::HTTPSuccess)

      JSON.parse(response.body)
    rescue JSON::ParserError, IOError, SystemCallError, Timeout::Error
      raise RuleError, '暂时无法确认生图任务，请稍后重试确认'
    end

    def self.store(user)
      data = PluginStore.get(NAMESPACE, "user-#{user.id}") || { 'date' => quota_day, 'submitted' => 0, 'tasks' => [], 'quota_schema' => 2 }
      unless data['quota_schema'] == 2
        data['tasks'].each do |task|
          task['quota_day'] ||= Time.iso8601(task['created_at']).in_time_zone('Asia/Shanghai').to_date.iso8601
          task['quota_reserved'] = task['status'] != 'error' unless task.key?('quota_reserved')
        end
        data['date'] = quota_day
        data['submitted'] = data['tasks'].count { |task| task['quota_day'] == quota_day && task['quota_reserved'] }
        data['quota_schema'] = 2
      end
      data
    end

    def self.quota_day
      Time.current.in_time_zone('Asia/Shanghai').to_date.iso8601
    end

    def self.save(user, data)
      PluginStore.set(NAMESPACE, "user-#{user.id}", data)
    end

    def self.public_task(task)
      task.slice('id', 'client_id', 'title', 'status', 'created_at', 'message', 'creation').merge(
        'images' => Array(task['urls']).each_index.map { |index| "/studio/api/generations/#{task['id']}/image?index=#{index}" }
      )
    end

    def self.submit(user, client_id:, prompt:, title:, ratio:, creation: nil)
      raise RuleError, '在线生图暂未开放' unless enabled?
      raise RuleError, '请先填写画面主题' unless prompt.to_s.length.between?(5, 120_000)
      raise RuleError, '请求标识无效' unless client_id.to_s.match?(/\A[0-9a-f-]{36}\z/)
      raise RuleError, '画幅比例无效' unless RATIOS.key?(ratio)

      task = nil
      digest = Digest::SHA256.hexdigest([prompt, ratio].join("\n"))
      user.with_lock do
        data = store(user)
        task = data['tasks'].find { |item| item['client_id'] == client_id }
        if task
          raise RuleError, '同一请求不能用于不同创作，请重新提交' unless task['digest'] == digest
        else
          if data['date'] != quota_day
            data['date'] = quota_day
            data['submitted'] = 0
          end
          raise RuleError, '今天的生图次数已用完，明天再来试试' if data['submitted'] >= SiteSetting.handraw_generation_daily_limit
          raise RuleError, '还有一张图片正在生成，请先等它完成' if data['tasks'].any? { |item| ACTIVE.include?(item['status']) }

          task = { 'id' => SecureRandom.uuid, 'client_id' => client_id, 'title' => title.to_s.first(120),
                   'prompt' => prompt, 'ratio' => ratio, 'digest' => digest, 'status' => 'queued',
                   'created_at' => Time.now.utc.iso8601, 'urls' => [], 'creation' => creation,
                   'quota_day' => quota_day, 'quota_reserved' => true }
          data['tasks'] = [task] + data['tasks'].first(19)
          data['submitted'] += 1
          save(user, data)
        end
      end
      dispatch(user, task['id'])
    end

    def self.dispatch(user, id)
      task = store(user)['tasks'].find { |item| item['id'] == id }
      raise Discourse::NotFound unless task
      return public_task(task) unless task['status'] == 'queued'

      result = request('/api/image-tasks/generations', payload: {
                         client_task_id: task['id'], prompt: task['prompt'], model: 'gpt-image-2',
                         size: RATIOS.fetch(task['ratio']), quality: 'auto'
                       })
      update(user, id, result)
    rescue RuleError => error
      user.with_lock do
        data = store(user)
        record = data['tasks'].find { |item| item['id'] == id }
        record['message'] = error.message if record
        save(user, data)
      end
      public_task(store(user)['tasks'].find { |item| item['id'] == id })
    end

    def self.update(user, id, result)
      user.with_lock do
        data = store(user)
        task = data['tasks'].find { |item| item['id'] == id }
        raise Discourse::NotFound unless task

        incoming = result['status']
        previous_status = task['status']
        return public_task(task) if %w[success error].include?(task['status']) && incoming != task['status']
        return public_task(task) if task['status'] == 'running' && incoming == 'queued'
        if %w[queued running success error].include?(incoming)
          task['status'] = incoming
          task['message'] = incoming == 'error' ? '本次生成未完成。可保留主题，调整后重新创作。' : ''
          task['urls'] = Array(result['data']).filter_map do |item|
            next unless item.is_a?(Hash) && item['url'].is_a?(String)

            uri = URI.parse(item['url']) rescue nil
            uri.to_s if uri && %w[http https].include?(uri.scheme) && %w[chatgpt2api.handraw-style.com 127.0.0.1].include?(uri.host) && uri.path.start_with?('/images/')
          end.first(4)
          task['status'] = 'error' if incoming == 'success' && task['urls'].empty?
          if task['status'] == 'error' && task['quota_reserved']
            data['submitted'] = [data['submitted'] - 1, 0].max if task['quota_day'] == data['date']
            task['quota_reserved'] = false
          end
        end
        save(user, data)
        if task['status'] == 'success' && previous_status != 'success'
          Array(task.dig('creation', 'assets')).each do |asset|
            ref = asset['ref'] || asset[:ref]
            next unless ref.to_s.start_with?('community:')
            record = Entry.visible.find_by(public_id: ref.delete_prefix('community:'))
            next unless record && record.user_id != user.id
            Event.create_or_find_by!(entry_id: record.id, user_id: user.id, kind: 'reuse', day: quota_day) do |event|
              event.qualified = Access.qualified?(user)
            end
          end
        end
        public_task(task)
      end
    end

    def self.list(user, refresh: false)
      data = store(user)
      pending = data['tasks'].select { |task| ACTIVE.include?(task['status']) }
      if refresh && pending.any?
        result = request("/api/image-tasks?ids=#{pending.map { |task| task['id'] }.join(',')}")
        Array(result['items']).each { |item| update(user, item['id'], item) if pending.any? { |task| task['id'] == item['id'] } }
        data = store(user)
      end
      used = data['date'] == quota_day ? data['submitted'] : 0
      { tasks: data['tasks'].map { |task| public_task(task) }, remaining: [SiteSetting.handraw_generation_daily_limit - used, 0].max }
    end

    def self.image(user, id, index)
      task = store(user)['tasks'].find { |item| item['id'] == id }
      raise Discourse::NotFound unless task

      url = Array(task['urls'])[index.to_i]
      raise Discourse::NotFound unless url && index.to_s.match?(/\A[0-3]\z/)

      source = URI(url)
      uri = URI("http://127.0.0.1:8000#{source.request_uri}")
      response = Net::HTTP.start(uri.host, uri.port, nil, open_timeout: 3, read_timeout: 30) do |http|
        bytes = +''.b
        media_type = nil
        http.request(Net::HTTP::Get.new(uri)) do |result|
          raise Discourse::NotFound unless result.is_a?(Net::HTTPSuccess)
          media_type = result['Content-Type'].to_s.split(';').first
          raise Discourse::NotFound if %w[image/png image/jpeg image/webp].exclude?(media_type)
          result.read_body do |chunk|
            bytes << chunk
            raise RuleError, '图片过大，请稍后下载' if bytes.bytesize > 25.megabytes
          end
        end
        [bytes, media_type]
      end
      response
    end
  end
end
