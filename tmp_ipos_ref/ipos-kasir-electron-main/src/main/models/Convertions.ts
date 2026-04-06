import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface ConvertionInterface {
  product_id: number
  unit_id: number
  name?: string
  sell_price?: number
  stock?: number
}

class ConvertionModel extends Model {
  private table = 'convertions'
  private foreignKeys = [
    {
      column: 'product_id',
      referencedTable: 'products',
      referencedColumn: 'id',
      selectColumns: ['id', 'barcode', 'name', 'is_stock_variant', 'stock']
    },
    {
      column: 'unit_id',
      referencedTable: 'units',
      referencedColumn: 'id',
      selectColumns: ['id', 'name', 'factor']
    }
  ]

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: ConvertionInterface[]): Promise<any> {
    return await this.query(this.table, data)
  }

  async insertMany(data: ConvertionInterface[]): Promise<any> {
    return await this.queryMany(this.table, data)
  }

  async getAll(): Promise<any> {
    const response = await this.fetch(this.table, this.foreignKeys)
    return response
  }

  async getOne(id: number): Promise<any> {
    return await this.fetchById(this.table, id)
  }

  async findData(field: string, value: any): Promise<any> {
    return await this.fetchByField(this.table, field, value, this.foreignKeys)
  }

  async findDataByFields(field: string[], value: any): Promise<any> {
    return await this.fetchByFields(this.table, field, value, this.foreignKeys)
  }

  async searchData(field: string, value: string): Promise<any> {
    return await this.search(this.table, [field], value)
  }

  async updateData(id: number, payload: any): Promise<any> {
    return await this.update(this.table, id, payload)
  }

  async updateManyData(paramId: string[], payload: any[]): Promise<any> {
    return await this.updateMany(this.table, paramId, payload)
  }

  async deleteData(id: number): Promise<any> {
    return await this.delete(this.table, id)
  }
}

export default ConvertionModel
