import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface CategoryInterface {
  code?: string
  name?: string
}

class CategoryModel extends Model {
  private table = 'categories'
  private index = ['']

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: CategoryInterface[]): Promise<any> {
    return await this.query(this.table, data)
  }
  async insertMany(data: CategoryInterface[]): Promise<any> {
    return await this.queryMany(this.table, data)
  }
  async getAll(): Promise<any> {
    return await this.fetch(this.table)
  }

  async getOne(id: number): Promise<any> {
    return await this.fetchById(this.table, id)
  }

  async searchData(param: string): Promise<any> {
    return await this.search(this.table, this.index, param)
  }

  async updateData(id: number, payload: any): Promise<any> {
    return await this.update(this.table, id, payload)
  }

  async deleteData(id: number): Promise<any> {
    return await this.delete(this.table, id)
  }
}

export default CategoryModel
