# frozen_string_literal: true

class CreateHandrawCommunity < ActiveRecord::Migration[8.0]
  def change
    create_table :handraw_entries do |table|
      table.string :public_id, null: false
      table.bigint :user_id, null: false
      table.bigint :topic_id, null: false
      table.string :kind, null: false
      table.string :title, null: false
      table.text :summary, null: false
      table.string :cover_url, null: false, default: ''
      table.text :license, null: false
      table.string :version, null: false, default: '1.0.0'
      table.string :content_digest, null: false
      table.string :status, null: false, default: 'published'
      table.boolean :featured, null: false, default: false
      table.boolean :verified, null: false, default: false
      table.boolean :download_approved, null: false, default: false
      table.boolean :paid_opt_in, null: false, default: false
      table.integer :price, null: false, default: 10
      table.integer :price_revision, null: false, default: 1
      table.string :price_reason, null: false, default: '初始价格'
      table.datetime :last_priced_at
      table.string :bundle_key, null: false, default: ''
      table.string :bundle_sha256, null: false, default: ''
      table.string :bundle_filename, null: false, default: 'resource.zip'
      table.bigint :bundle_bytes, null: false, default: 0
      table.jsonb :metadata, null: false, default: {}
      table.timestamps null: false
    end
    add_index :handraw_entries, :public_id, unique: true
    add_index :handraw_entries, :content_digest, unique: true
    add_index :handraw_entries, :topic_id, unique: true
    add_index :handraw_entries, %i[status kind created_at]
    add_index :handraw_entries, %i[user_id created_at]
    add_index :handraw_entries, :bundle_sha256, unique: true, where: "bundle_sha256 <> ''"
    add_check_constraint :handraw_entries, 'price BETWEEN 5 AND 30 AND price % 5 = 0', name: 'handraw_price_range'

    create_table :handraw_wallets do |table|
      table.bigint :user_id, null: false
      table.integer :balance, null: false, default: 0
      table.boolean :locked, null: false, default: false
      table.timestamps null: false
    end
    add_index :handraw_wallets, :user_id, unique: true

    create_table :handraw_ledgers do |table|
      table.bigint :user_id, null: false
      table.bigint :entry_id
      table.integer :amount, null: false
      table.string :event_key, null: false
      table.string :reason, null: false
      table.timestamps null: false
    end
    add_index :handraw_ledgers, %i[user_id event_key], unique: true
    add_index :handraw_ledgers, %i[user_id created_at]
    add_index :handraw_ledgers, %i[entry_id event_key]

    create_table :handraw_collections do |table|
      table.bigint :user_id, null: false
      table.bigint :entry_id, null: false
      table.timestamps null: false
    end
    add_index :handraw_collections, %i[user_id entry_id], unique: true
    add_index :handraw_collections, :entry_id

    create_table :handraw_events do |table|
      table.bigint :user_id, null: false
      table.bigint :entry_id, null: false
      table.string :kind, null: false
      table.boolean :qualified, null: false, default: false
      table.date :day, null: false
      table.timestamps null: false
    end
    add_index :handraw_events, %i[entry_id user_id kind day], unique: true, name: 'handraw_event_daily_unique'
    add_index :handraw_events, %i[entry_id kind qualified created_at], name: 'handraw_event_metrics'

    create_table :handraw_unlocks do |table|
      table.bigint :user_id, null: false
      table.bigint :author_id, null: false
      table.bigint :entry_id, null: false
      table.integer :amount, null: false
      table.integer :author_amount, null: false
      table.datetime :settle_at, null: false
      table.datetime :settled_at
      table.datetime :refunded_at
      table.boolean :held, null: false, default: false
      table.timestamps null: false
    end
    add_index :handraw_unlocks, %i[user_id entry_id], unique: true
    add_index :handraw_unlocks, %i[settle_at settled_at]
    add_index :handraw_unlocks, :entry_id
    add_index :handraw_unlocks, :author_id
    add_check_constraint :handraw_unlocks, 'amount >= 0 AND author_amount >= 0 AND author_amount <= amount',
                         name: 'handraw_unlock_amounts'

    create_table :handraw_audits do |table|
      table.bigint :user_id, null: false
      table.bigint :entry_id
      table.string :action, null: false
      table.text :reason, null: false
      table.jsonb :details, null: false, default: {}
      table.timestamps null: false
    end
    add_index :handraw_audits, %i[entry_id created_at]

    create_table :handraw_reports do |table|
      table.bigint :user_id, null: false
      table.bigint :entry_id, null: false
      table.text :reason, null: false
      table.string :status, null: false, default: 'open'
      table.timestamps null: false
    end
    add_index :handraw_reports, %i[user_id entry_id], unique: true
    add_index :handraw_reports, %i[status created_at]

    create_table :handraw_price_changes do |table|
      table.bigint :entry_id, null: false
      table.integer :old_price, null: false
      table.integer :new_price, null: false
      table.string :reason, null: false
      table.timestamps null: false
    end
    add_index :handraw_price_changes, %i[entry_id created_at]
  end
end
