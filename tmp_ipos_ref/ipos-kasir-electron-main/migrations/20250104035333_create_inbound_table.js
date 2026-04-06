/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('inbounds', function (table) {
    table.increments('id').primary()
    table.integer('product_id').unsigned().notNullable()
    table.integer('quantity').notNullable()
    table.integer('unit_id').nullable().references('id').inTable('units')
    table.date('received_date').notNullable()
    table.string('supplier').nullable()

    table.foreign('product_id').references('id').inTable('products').onDelete('CASCADE')
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('inbounds')
}
