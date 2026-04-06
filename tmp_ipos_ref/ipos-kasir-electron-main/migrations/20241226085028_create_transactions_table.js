/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('transactions', (table) => {
    table.uuid('id').primary()
    table
      .integer('product_id')
      .references('id')
      .inTable('products')
      .index('idx_product_transaction')
    table.uuid('invoice_id').references('id').inTable('invoices').index('idx_invoice_transaction')
    table.integer('discount_id').nullable()
    table.integer('tax_id').nullable()
    table.integer('unit_id').references('id').inTable('units')
    table.integer('product_qty').notNullable()
    table.decimal('total_price').notNullable()
    table.dateTime('order_date').notNullable().index('idx_order_date_transaction')
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('transactions')
}
