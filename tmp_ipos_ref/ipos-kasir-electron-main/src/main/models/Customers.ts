import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface CustomerInterface {
  name: string
  phone?: string
  address?: string
  points: number
}

class CustomerModel extends Model {
  private table = 'customers'
  private index = ['name']

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: CustomerInterface): Promise<any> {
    return await this.query(this.table, data)
  }

  async insertMany(data: CustomerInterface[]): Promise<any> {
    return await this.queryMany(this.table, data)
  }

  async getAll(): Promise<any> {
    const response = await this.fetch(this.table)
    return response
  }

  async getPaginated(page: number, limit: number): Promise<any> {
    const response = await this.fetchByLimit(this.table, page, limit)
    return response
  }

  async getOne(id: number): Promise<any> {
    return await this.fetchById(this.table, id)
  }

  async searchData(param: string): Promise<any> {
    return await this.search(this.table, this.index, param)
  }

  async countData(): Promise<any> {
    return await this.count(this.table)
  }

  async updateData(id: number, payload: any): Promise<any> {
    return await this.update(this.table, id, payload)
  }

  async deleteData(id: number): Promise<any> {
    console.log('DELETEEEEEEEEEEEEEEEEEEEEEE')
    console.log(id)
    return await this.delete(this.table, id)
  }
}

export default CustomerModel
