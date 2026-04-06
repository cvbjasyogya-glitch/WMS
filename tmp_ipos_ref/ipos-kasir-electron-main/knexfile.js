// knexfile.js
require('dotenv').config()

module.exports = {
  client: 'sqlite3',
  connection: {
    filename: `./db/${process.env.VITE_LOCALDB}.db`
  },
  useNullAsDefault: true
}
