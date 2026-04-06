import CustomerModel, { CustomerInterface } from '../models/Customers'
import { db } from '../services/database/db_conn'
import { handleDatabaseError } from '../utils/error-handler'

const Customers = new CustomerModel(db)

export const fetchAllCustomers = async () => {
  try {
    const data = await Customers.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchLimitCustomers = async (page: number, limit: number) => {
  try {
    const offset = (page - 1) * limit
    const data = await Customers.getPaginated(offset, limit)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const countCustomers = async () => {
  try {
    const data = await Customers.countData()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneCustomers = async (id: number) => {
  try {
    const data = await Customers.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchCustomers = async (param: string) => {
  try {
    const data = await Customers.searchData(param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateCustomers = async (id: number, data: any) => {
  try {
    console.log('UPDATEEEEE')
    console.log(data)
    const response = await Customers.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertCustomers = async (data: CustomerInterface) => {
  try {
    const response = await Customers.insert(data)
    console.log(response)
    if (response != true) return response
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertManyCustomers = async (data: CustomerInterface[]) => {
  try {
    const response = await Customers.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteCustomers = async (id: number) => {
  try {
    const response = await Customers.deleteData(id)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
