import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface TransactionInterface {
  id: string
  product_id: number
  product_qty: number
  invoice_id: string
  unit_id: number
  total_price: number
  order_date: string
  discount_id?: number
  tax_id?: number
}

class TransactModel extends Model {
  private table = 'transactions'
  private index = ['product_id', 'order_date']
  private foreignKeys = [
    {
      column: 'product_id',
      referencedTable: 'products',
      referencedColumn: 'id',
      selectColumns: ['id', 'name', 'barcode', 'stock', 'purchase_price']
    },
    {
      column: 'unit_id',
      referencedTable: 'units',
      referencedColumn: 'id',
      selectColumns: ['id', 'name', 'factor']
    },
    {
      column: 'invoice_id',
      referencedTable: 'invoices',
      referencedColumn: 'id',
      foreignKey: [
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
      ],
      selectColumns: ['id', 'customer_id', 'staff_id', 'total_price', 'total_profit', 'order_date']
    }
  ]

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: TransactionInterface): Promise<any> {
    return await this.query(this.table, data)
  }

  async insertMany(data: TransactionInterface[]): Promise<any> {
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

export default TransactModel
