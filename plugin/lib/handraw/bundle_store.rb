# frozen_string_literal: true

require 'zip'
require 'digest'
require 'fileutils'

module Handraw
  module BundleStore
    def self.root
      Pathname.new(ENV['HANDRAW_PRIVATE_STORAGE'].presence || SiteSetting.handraw_private_storage).expand_path
    end

    def self.validate!(path, expected_kind)
      raise RuleError, '资源包超过大小限制' if File.size(path) > SiteSetting.handraw_max_bundle_megabytes.megabytes

      Zip::File.open(path) do |archive|
        raise RuleError, '资源包文件过多' if archive.entries.size > 1000

        total = 0
        archive.each do |item|
          name = item.name.tr('\\', '/')
          if name.start_with?('/') || name.include?(':') || name.split('/').include?('..') || item.ftype == :symlink
            raise RuleError, '资源包包含不安全路径'
          end

          total += item.size
        end
        raise RuleError, '解压后资源过大' if total > 100.megabytes

        manifest_file = archive.find_entry('manifest.json')
        raise RuleError, '缺少 manifest.json' unless manifest_file && manifest_file.size <= 1.megabyte

        manifest = JSON.parse(manifest_file.get_input_stream.read)
        resource = manifest['resource']
        unless manifest['schema_version'] == 1 && resource.is_a?(Hash) &&
               resource['kind'] == expected_kind && resource['license'].to_s.length.between?(5, 2000)
          raise RuleError, '资源清单类型或授权不完整'
        end
        if %w[style layout].include?(expected_kind) &&
           (resource['prompt_zh'].to_s.strip.empty? || resource['prompt_en'].to_s.strip.empty?)
          raise RuleError, '画风与图型需要完整的中英文定义'
        end

        manifest
      end
    rescue Zip::Error, JSON::ParserError
      raise RuleError, '无法读取 ZIP 资源包或清单'
    end

    def self.save!(entry, file)
      path = file.tempfile.path
      manifest = validate!(path, entry.kind)
      sha = Digest::SHA256.file(path).hexdigest
      raise RuleError, '该资源包已经发布，请更新原投稿' if Entry.where.not(id: entry.id).exists?(bundle_sha256: sha)

      FileUtils.mkdir_p(root, mode: 0o700)
      key = "#{entry.public_id}-#{sha}.zip"
      destination = root.join(key)
      FileUtils.copy_file(path, destination)
      File.chmod(0o600, destination)
      entry.with_lock do
        entry.update!(
          bundle_key: key,
          bundle_sha256: sha,
          bundle_bytes: File.size(destination),
          bundle_filename: "#{entry.kind}-#{entry.public_id}.zip",
          version: manifest.fetch('resource').fetch('version', '1.0.0').to_s.first(40),
          featured: false,
          verified: false,
          download_approved: false,
          metadata: entry.metadata.merge('examples' => manifest.dig('resource', 'examples'))
        )
      end
      manifest
    end

    def self.path(entry)
      candidate = root.join(entry.bundle_key).cleanpath
      raise RuleError, '资源文件不可用' unless candidate.dirname == root && candidate.file?
      raise RuleError, '资源文件校验失败' unless Digest::SHA256.file(candidate).hexdigest == entry.bundle_sha256

      candidate
    end
  end
end
