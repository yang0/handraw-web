# frozen_string_literal: true

raise "Must use isolated test database" unless ActiveRecord::Base.connection.current_database == "handraw_web_test"
SiteSetting.handraw_enabled = true
SiteSetting.handraw_public_submissions = true
RateLimiter.disable
suffix = SecureRandom.hex(4)
author = User.create!(username: "hwa_#{suffix}", email: "hwa_#{suffix}@example.test", password: SecureRandom.base64(32), active: true)
buyer = User.create!(username: "hwb_#{suffix}", email: "hwb_#{suffix}@example.test", password: SecureRandom.base64(32), active: true)
category = Category.create!(name: "Concurrency #{suffix}", user: author, color: "0088CC", text_color: "FFFFFF")
resources = 3.times.map do |number|
  topic = Topic.create!(user: author, title: "Parallel resource #{suffix} #{number}", category: category)
  Handraw::Entry.create!(user: author, topic: topic, public_id: SecureRandom.uuid, kind: "package",
    title: "Parallel resource #{suffix} #{number}", summary: "Concurrent integration verification in an isolated database.",
    license: "Only for isolated test verification.", content_digest: SecureRandom.hex(32),
    bundle_key: "test.zip", bundle_sha256: SecureRandom.hex(32), paid_opt_in: true, download_approved: true)
end
Handraw::Wallet.change!(buyer.id, 10, key: "concurrency-seed", reason: "Isolated test credits")
ActiveRecord::Base.connection_pool.release_connection

def parallel_unlock(resources, buyer)
  errors = Queue.new
  gate = Queue.new
  threads = resources.map do |resource|
    Thread.new do
      gate.pop
      ActiveRecord::Base.connection_pool.with_connection do
        Handraw::Economy.unlock!(resource.class.find(resource.id), buyer, 10, 1)
      end
    rescue Handraw::RuleError => error
      errors << error.message
    end
  end
  resources.size.times { gate << true }
  threads.each(&:value)
  errors.size
end

retry_errors = parallel_unlock([resources.first, resources.first], buyer)
raise "Retry double charged" unless retry_errors.zero? && Handraw::Wallet.for_user(buyer.id).balance.zero?
raise "Duplicate entitlement" unless Handraw::Unlock.where(user_id: buyer.id).count == 1
Handraw::Wallet.change!(buyer.id, 10, key: "concurrency-second", reason: "Isolated test credits")
overspend_errors = parallel_unlock(resources.drop(1), buyer)
raise "Concurrent overspend" unless overspend_errors == 1 && Handraw::Wallet.for_user(buyer.id).balance.zero?
raise "Incorrect sale count" unless Handraw::Unlock.where(user_id: buyer.id).count == 2
puts JSON.generate(concurrent_retry: "passed", concurrent_overspend: "passed", final_balance: 0)
