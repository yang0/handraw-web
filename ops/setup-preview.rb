# frozen_string_literal: true

raise "Wrong database" unless ActiveRecord::Base.connection.current_database == "handraw_web_preview"
SiteSetting.handraw_enabled = true
SiteSetting.handraw_public_submissions = true
SiteSetting.force_https = false
SiteSetting.enable_local_logins = true
SiteSetting.login_required = false
SiteSetting.title = "手绘风 · 隔离预览"
puts "Preview database isolated and portal enabled. No production users copied."
