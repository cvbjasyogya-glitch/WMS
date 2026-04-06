/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('invoices', (table) => {
    table.uuid('id').primary()
    table
      .integer('customer_id')
      .references('id')
      .inTable('customers')
      .index('idx_customer_invoice')
      .nullable()
    table.integer('staff_id').references('id').inTable('users').index('idx_staff_invoice')
    table.decimal('total_price').notNullable()
    table.decimal('total_profit').notNullable()
    table.dateTime('order_date').notNullable().index('idx_date_invoice')
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('invoices')
}
