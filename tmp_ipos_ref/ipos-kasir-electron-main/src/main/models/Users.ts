import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface ResponseData {
  id: string
  name: string
  email: string
  role_id: number
}

export interface UserInterface {
  id?: number
  name?: string
  phone?: string
  supabase_id?: string
  email: string
  password: string
  created_at?: string
  updated_at?: string
}

class UserModel extends Model {
  private table = 'users'
  private index = ['name', 'email']

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: UserInterface): Promise<any> {
    return await this.query(this.table, data)
  }

  async getAll(): Promise<any> {
    return await this.fetch(this.table)
  }

  async getOne(id: number): Promise<any> {
    return await this.fetchById(this.table, id)
  }

  async find(value: any) {
    return await this.search(this.table, this.index, value)
  }

  async getOneByField(field: string, value: any): Promise<any> {
    return await this.fetchByField(this.table, field, value)
  }
}

export default UserModel
