import TransactModel, { TransactionInterface } from '../models/Transactions'
import { db } from '../services/database/db_conn'
import { handleDatabaseError } from '../utils/error-handler'

const Transactions = new TransactModel(db)

export const fetchAllTransactions = async () => {
  try {
    const data = await Transactions.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchLimitTransactions = async (
  page: number,
  limit: number,
  id?: number,
  field?: string,
  timeField?: string,
  start?: string,
  end?: string
) => {
  try {
    const offset = (page - 1) * limit
    const data = await Transactions.getPaginated(offset, limit, id, field, timeField, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const countTransactions = async (
  id?: number,
  field?: string,
  timeField?: string,
  start?: string,
  end?: string
) => {
  try {
    const data = await Transactions.countData(id, field, timeField, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneTransactions = async (id: number) => {
  try {
    const data = await Transactions.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchByFieldTransactions = async (field: string, value: any) => {
  try {
    const data = await Transactions.getByField(field, value)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchTransactions = async (param: string) => {
  try {
    const data = await Transactions.searchData(param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const filterTimeTransactions = async (field: string, start: string, end: string) => {
  try {
    const data = await Transactions.filterDataTime(field, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateTransactions = async (id: number, data: any) => {
  try {
    const response = await Transactions.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateManyTransactions = async (paramId: string[], data: any[]) => {
  try {
    const response = await Transactions.updateManyData(paramId, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertTransactions = async (data: TransactionInterface) => {
  try {
    const response = await Transactions.insert(data)
    console.log(response)
    if (response != true) return response
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertManyTransactions = async (data: TransactionInterface[]) => {
  try {
    const response = await Transactions.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteTransactions = async (id: number) => {
  try {
    const response = await Transactions.deleteData(id)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
