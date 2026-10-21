# frozen_string_literal: true

class AllowConfigurableHandrawPrices < ActiveRecord::Migration[8.0]
  def up
    remove_check_constraint :handraw_entries, name: 'handraw_price_range'
    add_check_constraint :handraw_entries, 'price >= 0', name: 'handraw_price_nonnegative'
  end

  def down
    raise ActiveRecord::IrreversibleMigration, 'Keep resource prices and ledgers when rolling back code'
  end
end
