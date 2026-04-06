const { now } = require('./utils/utils')

/**
 * @param { import("knex").Knex } knex
 * @returns { Promise<void> }
 */
exports.seed = async function (knex) {
  await knex('roles').insert([
    {
      role_name: 'super_admin',
      created_at: now(),
      updated_at: now()
    },
    {
      role_name: 'admin',
      created_at: now(),
      updated_at: now()
    },
    {
      role_name: 'user',
      created_at: now(),
      updated_at: now()
    }
  ])
}
