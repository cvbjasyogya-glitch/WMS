import InvoiceModel, { InvoiceInterface } from '../models/Invoices'
import { db } from '../services/database/db_conn'
import { handleDatabaseError } from '../utils/error-handler'

const Invoices = new InvoiceModel(db)

export const fetchAllInvoices = async () => {
  try {
    const data = await Invoices.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchLimitInvoices = async (
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
    const data = await Invoices.getPaginated(offset, limit, id, field, timeField, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const countInvoices = async (
  id?: number,
  field?: string,
  timeField?: string,
  start?: string,
  end?: string
) => {
  try {
    const data = await Invoices.countData(id, field, timeField, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneInvoices = async (id: number) => {
  try {
    const data = await Invoices.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchByFieldInvoices = async (field: string, value: any) => {
  try {
    const data = await Invoices.getByField(field, value)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchInvoices = async (param: string) => {
  try {
    const data = await Invoices.searchData(param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const filterTimeInvoice = async (field: string, start: string, end: string) => {
  try {
    const data = await Invoices.filterDataTime(field, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateInvoices = async (id: number, data: any) => {
  try {
    const response = await Invoices.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateManyInvoices = async (paramId: string[], data: any[]) => {
  try {
    const response = await Invoices.updateManyData(paramId, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertInvoices = async (data: InvoiceInterface) => {
  try {
    const response = await Invoices.insert(data)
    console.log(response)
    if (response != true) return response
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertManyInvoices = async (data: InvoiceInterface[]) => {
  try {
    const response = await Invoices.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteInvoices = async (id: number) => {
  try {
    const response = await Invoices.deleteData(id)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
