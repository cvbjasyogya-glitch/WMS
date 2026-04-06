import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface DiscountInterface {
  name: string
  value: number
}

class DiscountsModels extends Model {
  private table = 'discounts'
  private index = ['name']

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: DiscountInterface[]): Promise<any> {
    return await this.query(this.table, data)
  }

  async getAll(): Promise<any> {
    const response = await this.fetch(this.table)
    return response
  }

  async getOne(id: number): Promise<any> {
    return await this.fetchById(this.table, id)
  }

  async searchData(param: string): Promise<any> {
    return await this.search(this.table, this.index, param)
  }

  async deleteData(id: number): Promise<any> {
    return await this.delete(this.table, id)
  }
}

export default DiscountsModels
