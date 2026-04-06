import Model from './Models'
import SqliteDB from '../services/database/sqlite'

export interface ProductInterface {
  category_id: number
  barcode: string
  name: string
  stock: number
  purchase_price: number
  is_stock_variant: number
}

class ProductModel extends Model {
  private table = 'products'
  private index = ['name', 'barcode']
  private foreignKeys = [
    {
      column: 'category_id',
      referencedTable: 'categories',
      referencedColumn: 'id',
      selectColumns: ['id', 'code', 'name']
    }
  ]

  constructor(db: SqliteDB) {
    super(db)
  }

  async insert(data: ProductInterface[]): Promise<any> {
    return await this.query(this.table, data)
  }

  async insertMany(data: ProductInterface[]): Promise<any> {
    return await this.queryMany(this.table, data)
  }

  async getAll(): Promise<any> {
    const response = await this.fetch(this.table, this.foreignKeys)
    return response
  }

  async getPaginated(page: number, limit: number): Promise<any> {
    const response = await this.fetchByLimit(this.table, page, limit, this.foreignKeys)
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

  async updateManyData(paramId: string[], payload: any[]): Promise<any> {
    return await this.updateMany(this.table, paramId, payload)
  }

  async deleteData(id: number): Promise<any> {
    return await this.delete(this.table, id)
  }
}

export default ProductModel
