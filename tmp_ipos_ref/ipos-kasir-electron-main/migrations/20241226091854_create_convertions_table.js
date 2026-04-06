/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('convertions', (table) => {
    table.increments('id').primary()
    table
      .integer('product_id')
      .notNullable()
      .references('id')
      .inTable('products')
      .onDelete('CASCADE')
      .onUpdate('CASCADE')
      .index('idx_product_convertion')
    table.string('name').nullable().index('idx_convertion_name')
    table
      .integer('unit_id')
      .notNullable()
      .references('id')
      .inTable('units')
      .onDelete('CASCADE')
      .index('idx_unit_id')
    table.decimal('stock').defaultTo(0).nullable().index('idx_stock_convertion')
    table.decimal('sell_price').defaultTo(0).nullable()
    table.decimal('grosir').nullable().index('idx_grosir_convertion')
    table.decimal('grosir_price').nullable().index('idx_gosir_price')
    table.timestamps(true, true)
    table.unique(['product_id', 'unit_id'])
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('convertions')
}
