/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.up = function (knex) {
  return knex.schema.createTable('users', (table) => {
    table.increments('id').primary()
    table.uuid('supabase_id').nullable().unique()
    table
      .integer('role_id')
      .nullable()
      .references('id')
      .inTable('roles')
      .onDelete('SET NULL')
      .onUpdate('CASCADE')
      .index('idx_role_user')
    table.string('name').nullable().index('idx_name_user')
    table.string('email').notNullable().unique().index('idx_email_user')
    table.string('password').notNullable()
    table.string('phone').nullable().index('idx_phone_user')
    table.timestamps(true, true)
  })
}

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.down = function (knex) {
  return knex.schema.dropTable('users')
}
