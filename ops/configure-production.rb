# frozen_string_literal: true

raise "Wrong database" unless ActiveRecord::Base.connection.current_database == "discourse"
first_activation = !SiteSetting.handraw_enabled
if first_activation
  creators = Group.find_or_create_by!(name: "handraw_creators") do |group|
    group.full_name = "手绘风试运行创作者"
    group.visibility_level = Group.visibility_levels[:staff]
  end
  reviewers = Group.find_or_create_by!(name: "handraw_reviewers") do |group|
    group.full_name = "手绘风资源审核团队"
    group.visibility_level = Group.visibility_levels[:staff]
  end
  SiteSetting.handraw_pilot_group_ids = creators.id.to_s
  SiteSetting.handraw_reviewer_group_ids = reviewers.id.to_s
  SiteSetting.handraw_public_submissions = false
end
SiteSetting.handraw_enabled = true
puts "Portal enabled. Public discovery; publishing remains controlled by existing pilot settings."
