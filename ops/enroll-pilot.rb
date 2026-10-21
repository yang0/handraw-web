# frozen_string_literal: true

raise "Wrong database" unless ActiveRecord::Base.connection.current_database == "discourse"
username = ARGV.fetch(0)
user = User.find_by!(username: username)
actor = User.where(admin: true).where("id > 0").order(:id).first!
groups = ["handraw_creators"]
groups << "handraw_reviewers" if ARGV.include?("--reviewer")
Group.transaction do
  groups.each { |name| Group.find_by!(name: name).add(user) }
  Handraw::Audit.create!(user_id: actor.id, action: "enroll_pilot", reason: "网站维护者明确指定试运行成员及审核职责",
    details: { username: user.username, groups: groups })
end
puts JSON.generate(username: user.username, groups: groups, global_moderator_unchanged: true)
