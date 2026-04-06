import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface InvoiceInterface {
  customer_id: number
  staff_id: number
  trasaction_id: number
  total_price: number
  total_profit: number
  order_date: string
}

class InvoiceModel extends Model {
  private table = 'invoices'
  private index = ['product_id', 'customer_id', 'staff_id', 'transaction_id', 'order_date']
  private foreignKeys = [
    {
      column: 'customer_id',
      referencedTable: 'customers',
      referencedColumn: 'id',
      selectColumns: ['id', 'name', 'address', 'points', 'phone']
    },
    {
      column: 'staff_id',
      referencedTable: 'users',
      referencedColumn: 'id',
      selectColumns: ['id', 'name', 'email', 'phone']
    }
  ]

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: InvoiceInterface): Promise<any> {
    return await this.query(this.table, data)
  }

  async insertMany(data: InvoiceInterface[]): Promise<any> {
    return await this.queryMany(this.table, data)
  }

  async getAll(): Promise<any> {
    const response = await this.fetch(this.table, this.foreignKeys)
    return response
  }

  async getByField(field: string, value: string): Promise<any> {
    const response = await this.fetchByField(this.table, field, value, this.foreignKeys)
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

export default InvoiceModel
