# frozen_string_literal: true

class AddHandrawContentMarket < ActiveRecord::Migration[8.0]
  def up
    add_column :handraw_entries, :pricing_mode, :string, null: false, default: 'legacy'
    create_table :handraw_contents do |t|
      t.bigint :entry_id, null: false
      t.jsonb :data, null: false, default: {}
      t.timestamps null: false
    end
    add_index :handraw_contents, :entry_id, unique: true
    create_table :handraw_asset_links do |t|
      t.bigint :entry_id, null: false
      t.string :asset_ref, null: false
      t.string :kind, null: false
      t.string :role, null: false
      t.string :version, null: false
      t.timestamps null: false
    end
    add_index :handraw_asset_links, %i[entry_id asset_ref], unique: true
    add_index :handraw_asset_links, :asset_ref
    create_table :handraw_asset_collections do |t|
      t.bigint :user_id, null: false
      t.string :asset_ref, null: false
      t.timestamps null: false
    end
    add_index :handraw_asset_collections, %i[user_id asset_ref], unique: true
    create_table :handraw_private_images do |t|
      t.string :public_id, null: false
      t.bigint :user_id, null: false
      t.bigint :entry_id
      t.string :storage_key, null: false
      t.string :media_type, null: false
      t.bigint :bytes, null: false
      t.timestamps null: false
    end
    add_index :handraw_private_images, :public_id, unique: true
    add_index :handraw_private_images, :entry_id
  end

  def down
    raise ActiveRecord::IrreversibleMigration, 'Keep private contents, relationships and entitlements when rolling back code'
  end
end
