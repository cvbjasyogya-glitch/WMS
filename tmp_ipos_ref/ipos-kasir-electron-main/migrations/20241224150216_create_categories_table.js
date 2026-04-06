/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('categories', (table) => {
    table.increments('id').primary()
    table.string('code').notNullable().unique().index('idx_category_code')
    table.string('name').notNullable().index('idx_category_name')
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('categories')
}
