# frozen_string_literal: true

# Reviewed existing initializer; live file remains untouched.
Rails.application.config.after_initialize do
  UrlHelper.singleton_class.prepend(Module.new do
    def local_cdn_url(url)
      upload_cdn = ENV["DISCOURSE_UPLOAD_CDN_URL"].presence || "https://img.handraw-style.com"
      if upload_cdn.present? && url.start_with?("/#{Discourse.store.upload_path}/")
        "#{upload_cdn}#{url}"
      else
        super
      end
    end
  end)
end
