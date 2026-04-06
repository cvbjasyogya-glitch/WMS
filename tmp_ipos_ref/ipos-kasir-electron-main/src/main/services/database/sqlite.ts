import sqlite from 'sqlite-electron'
import bcrypt from 'bcrypt'

class SqliteDB {
  private static instance: SqliteDB
  private dbFilePath: string

  constructor(dbFilePath: string) {
    this.dbFilePath = dbFilePath
  }

  public static getInstance(dbFilePath: string): SqliteDB {
    if (!SqliteDB.instance) {
      SqliteDB.instance = new SqliteDB(dbFilePath)
    }
    return SqliteDB.instance
  }

  async connect(): Promise<void> {
    try {
      const isConnected = await sqlite.setdbPath(this.dbFilePath)
      if (isConnected) {
        await sqlite.executeQuery('PRAGMA foreign_keys = ON')
        await this.insertDefaultUser()
        return await sqlite.fetchOne('SELECT 1')
      }
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  private async insertDefaultUser(): Promise<void> {
    const userExists = await sqlite.fetchOne<{ count: number }>(
      'SELECT COUNT(*) as count FROM users WHERE email = ?',
      ['admin']
    )

    if (userExists && userExists.count === 0) {
      const hashedPassword = await bcrypt.hash('admin', 10)

      await sqlite.executeQuery('INSERT INTO users (email,name, password) VALUES (?, ?, ?)', [
        'admin',
        'admin',
        hashedPassword
      ])
    }
  }
}

export default SqliteDB
