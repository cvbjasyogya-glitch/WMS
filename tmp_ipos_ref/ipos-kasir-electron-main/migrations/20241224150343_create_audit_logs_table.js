/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('audit_logs', (table) => {
    table.increments('id').primary()
    table
      .integer('user_id')
      .notNullable()
      .references('id')
      .inTable('users')
      .onDelete('CASCADE')
      .onUpdate('CASCADE')
      .index('idx_user_logs')
    table.string('table_name').notNullable().index('idx_table_logs')
    table.json('data_before').nullable()
    table.json('data_after').nullable()
    table.string('action').notNullable()
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTableIfExists('audit_logs')
}
