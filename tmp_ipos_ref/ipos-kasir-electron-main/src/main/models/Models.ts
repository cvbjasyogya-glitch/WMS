import SqliteDB from '../services/database/sqlite'
import { executeMany, executeQuery, fetchAll, fetchOne } from 'sqlite-electron'
import chalk from 'chalk'

import {
  countQuery,
  deleteQuery,
  fetchAllQuery,
  fetchByFieldQuery,
  fetchByFieldsQuery,
  fetchByIdQuery,
  fetchLimitQuery,
  insertManyQuery,
  insertQuery,
  queryFilterTimestamp,
  searchQuery,
  updateManyQuery,
  updateQuery
} from '../utils/query'
import { getCurrentTimestamp } from '../../renderer/src/utils/utils'

abstract class Model {
  protected db: SqliteDB

  constructor(db: SqliteDB) {
    this.db = db
  }

  protected async query(table: string, data: Record<string, any>): Promise<any> {
    try {
      const query = insertQuery(table, data)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      const params = Object.values(data).filter((value) => value !== undefined)
      const response = await executeQuery(query, params)
      return response
    } catch (error) {
      if (error instanceof Error) {
        throw error.message
      }
    }
  }

  protected async queryMany(table: string, data: Array<Record<string, any>>): Promise<any> {
    try {
      const query = insertManyQuery(table, data)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))

      const params: any[][] = data.map((record) => {
        return Object.keys(record).map((key) => record[key])
      })
      console.log(data)
      console.log('Parameters for SQL execution:', params)

      const response = await executeMany(query, params)
      return response
    } catch (error) {
      if (error instanceof Error) {
        throw error.message
      }
    }
  }

  protected async count(
    table: string,
    id?: number,
    field?: string,
    timeField?: string,
    start?: string,
    end?: string
  ): Promise<any> {
    try {
      const query = countQuery(table, id, field, timeField, start, end)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      if (id && id != -1 && field && field != null) {
        if (start && start != '' && end && end != '') return await fetchOne(query, [id, start, end])
        if (start && start != '') return await fetchOne(query, [id, start])
        if (end && end != '') return await fetchOne(query, [id, end])
        return await fetchOne(query, [id])
      } else {
        if (start && start != '' && end && end != '') {
          console.log('start', 'end')
          return await fetchOne(query, [start, end])
        }
        if (start && start != '') {
          console.log('start')
          return await fetchOne(query, [start])
        }
        if (end && end != '') {
          console.log('end')
          return await fetchOne(query, [end])
        }
        console.log('else')
        return await fetchOne(query)
      }
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async fetch(
    table: string,
    foreignKeys: {
      column: string
      referencedTable: string
      referencedColumn: string
      selectColumns?: string[]
    }[] = []
  ): Promise<any> {
    try {
      const query = fetchAllQuery(table, foreignKeys)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      return await fetchAll(query)
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async fetchById(table: string, id: any): Promise<any> {
    try {
      const query = fetchByIdQuery(table, id)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      return await fetchOne(query)
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async fetchByField(
    table: string,
    field: string,
    value: any,
    foreignKeys?: any
  ): Promise<any> {
    try {
      const query = fetchByFieldQuery(table, field, foreignKeys)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      return await fetchAll(query, [value])
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async fetchByFields(
    table: string,
    field: string[],
    value: any[],
    foreignKeys?: any
  ): Promise<any> {
    try {
      const query = fetchByFieldsQuery(table, field, foreignKeys)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      console.log(value)
      return await fetchAll(query, value)
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async fetchByLimit(
    table: string,
    page: number,
    limit: number,
    foreignKeys?: any,
    id?: number,
    field?: string,
    timeField?: string,
    start?: string,
    end?: string
  ): Promise<any> {
    try {
      const offset = page
      const query = fetchLimitQuery(table, foreignKeys, id, field, timeField, start, end)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      if (id && id != -1 && field && field != null) {
        if (start && start != '' && end && end != '') {
          console.log('start', 'end')
          return await fetchAll(query, [id, start, end, limit, offset])
        }
        if (start && start != '') {
          console.log('start')
          return await fetchAll(query, [id, start, limit, offset])
        }
        if (end && end != '') {
          console.log('end')
          return await fetchAll(query, [id, end, limit, offset])
        }
        return await fetchAll(query, [id, limit, offset])
      } else {
        if (start && start != '' && end && end != '') {
          console.log('start', 'end')
          return await fetchAll(query, [start, end, limit, offset])
        }
        if (start && start != '') {
          console.log('start')
          return await fetchAll(query, [start, limit, offset])
        }
        if (end && end != '') {
          console.log('end')
          return await fetchAll(query, [end, limit, offset])
        }
        const response = await fetchAll(query, [limit, offset])
        return response
      }
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async search(table: string, fields: string[], value: any): Promise<any> {
    try {
      const query = searchQuery(table, fields)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      const searchValue = `%${value}%`
      return await fetchAll(query, [searchValue])
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async fiterTimestamp(
    table: string,
    field: string,
    start: string,
    end: string,
    foreignKeys?: any
  ): Promise<any> {
    try {
      const query = queryFilterTimestamp(table, field, start, end, foreignKeys)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      if (start == '') return await fetchAll(query, [end])
      if (end == '') return await fetchAll(query, [start])
      return await fetchAll(query, [start, end])
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async update(table: string, id: any, data: any): Promise<any> {
    try {
      const query = updateQuery(table, data)
      const values = [...Object.values(data), id]
      console.log(values)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      return await executeQuery(query, values)
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }

  protected async updateMany(table: string, paramId: string[], data: Array<any>): Promise<any> {
    try {
      const query = updateManyQuery(table, paramId, data)
      const keys = Object.keys(data[0])
      const values: any[][] = data.map((item) => keys.map((key) => item[key]))

      console.log(values)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      return await executeMany(query, values)
    } catch (error) {
      console.log(error)
      if (error instanceof Error) throw error.message
    }
  }
  protected async delete(table: string, id: any): Promise<any> {
    try {
      const query = deleteQuery(table)
      console.log(chalk.green(`[INFO] ${getCurrentTimestamp()}: ${query}`))
      const response = await executeQuery(query, [id])
      return response
    } catch (error) {
      if (error instanceof Error) throw error.message
    }
  }
}

export default Model
