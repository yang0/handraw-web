# frozen_string_literal: true

require 'fileutils'

module Handraw
  module PrivateMedia
    def self.root
      BundleStore.root.join('images')
    end

    def self.save!(user, upload)
      bytes = upload.tempfile.read(10.megabytes + 1)
      raise RuleError, '正文图片不得超过 10 MB' if bytes.bytesize > 10.megabytes
      type = if bytes.start_with?("\x89PNG\r\n\x1a\n".b)
               'image/png'
             elsif bytes.start_with?("\xff\xd8\xff".b)
               'image/jpeg'
             elsif bytes.start_with?('RIFF') && bytes.byteslice(8, 4) == 'WEBP'
               'image/webp'
             end
      raise RuleError, '仅支持 PNG、JPEG、WebP 图片' unless type
      id = SecureRandom.uuid
      FileUtils.mkdir_p(root, mode: 0o700)
      path = root.join(id)
      File.binwrite(path, bytes)
      File.chmod(0o600, path)
      PrivateImage.create!(public_id: id, user_id: user.id, storage_key: id, media_type: type, bytes: bytes.bytesize)
    end

    def self.path(image)
      raise Discourse::NotFound unless image.storage_key.match?(/\A[0-9a-f-]{36}\z/)
      path = root.join(image.storage_key)
      raise Discourse::NotFound unless path.file?
      path
    end
  end
end
