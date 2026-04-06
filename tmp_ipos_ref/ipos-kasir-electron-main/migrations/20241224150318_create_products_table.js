/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('products', (table) => {
    table.increments('id').primary()
    table.string('name').notNullable().index('idx_product_nme')
    table
      .integer('category_id')
      .notNullable()
      .references('id')
      .inTable('categories')
      .onUpdate('CASCADE')
      .index('idx_category_product')
    table.string('barcode').notNullable().unique().index('idx_barcode_product')
    table.decimal('stock').defaultTo(0).notNullable()
    table.boolean('is_stock_variant').defaultTo(false).notNullable()
    table.decimal('purchase_price').defaultTo(0).notNullable()
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('products')
}
