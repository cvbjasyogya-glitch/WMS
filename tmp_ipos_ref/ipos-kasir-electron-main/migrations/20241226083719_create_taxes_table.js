/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('taxes', (table) => {
    table.increments('id').primary()
    table.string('name').notNullable().index('idx_tax_name')
    table.decimal('value').notNullable().index('idx_tax_value')
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('taxes')
}
