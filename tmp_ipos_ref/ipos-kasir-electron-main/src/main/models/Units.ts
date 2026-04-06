import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface UnitInterface {
  name: string
  factor: string
}

class UnitModel extends Model {
  private table = 'units'

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: UnitInterface[]): Promise<any> {
    return await this.query(this.table, data)
  }

  async insertMany(data: UnitInterface[]): Promise<any> {
    return await this.queryMany(this.table, data)
  }

  async getAll(): Promise<any> {
    return await this.fetch(this.table)
  }

  async getOne(id: number): Promise<any> {
    return await this.fetchById(this.table, id)
  }

  async updateData(id: number, payload: any): Promise<any> {
    return this.update(this.table, id, payload)
  }

  async deleteData(id: number): Promise<any> {
    return await this.delete(this.table, id)
  }
}

export default UnitModel
