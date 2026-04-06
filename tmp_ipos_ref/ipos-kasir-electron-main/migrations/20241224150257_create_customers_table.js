/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('customers', (table) => {
    table.increments('id').primary()
    table.string('name').notNullable().unique().index('idx_customer_name')
    table.string('phone').nullable().unique().index('idx_customer_phone')
    table.string('address').nullable().index('idx_customer_address')
    table.integer('points').defaultTo(0).index('idx_customer_points')
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('customers')
}
