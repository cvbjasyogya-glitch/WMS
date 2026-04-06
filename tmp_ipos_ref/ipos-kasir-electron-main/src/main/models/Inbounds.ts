import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface InboundInterface {
  product_id: number
  unit_id: number
  quantity: number
  supplier?: string
  received_date: string
}

class InboundModel extends Model {
  private table = 'inbounds'
  private index = ['product_id', 'received_date']
  private foreignKeys = [
    {
      column: 'product_id',
      referencedTable: 'products',
      referencedColumn: 'id',
      selectColumns: ['id', 'name', 'barcode', 'stock']
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

  async insert(data: InboundInterface): Promise<any> {
    return await this.query(this.table, data)
  }

  async insertMany(data: InboundInterface[]): Promise<any> {
    return await this.queryMany(this.table, data)
  }

  async getAll(): Promise<any> {
    const response = await this.fetch(this.table, this.foreignKeys)
    return response
  }

  async getPaginated(
    page: number,
    limit: number,
    id?: number,
    field?: string,
    timeField?: string,
    start?: string,
    end?: string
  ): Promise<any> {
    const response = await this.fetchByLimit(
      this.table,
      page,
      limit,
      this.foreignKeys,
      id,
      field,
      timeField,
      start,
      end
    )
    return response
  }

  async getOne(id: number): Promise<any> {
    return await this.fetchById(this.table, id)
  }

  async searchData(param: string): Promise<any> {
    return await this.search(this.table, this.index, param)
  }

  async filterDataTime(field: string, start: string, end: string): Promise<any> {
    return await this.fiterTimestamp(this.table, field, start, end, this.foreignKeys)
  }

  async countData(
    id?: number,
    field?: string,
    timeField?: string,
    start?: string,
    end?: string
  ): Promise<any> {
    return await this.count(this.table, id, field, timeField, start, end)
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

export default InboundModel
