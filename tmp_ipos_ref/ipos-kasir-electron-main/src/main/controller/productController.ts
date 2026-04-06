import { db } from '../services/database/db_conn'
import ProductModel, { ProductInterface } from '../models/Products'
import { handleDatabaseError } from '../utils/error-handler'

const Products = new ProductModel(db)

export const fetchAllProducts = async () => {
  try {
    const data = await Products.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchLimitProducts = async (page: number, limit: number) => {
  try {
    const offset = (page - 1) * limit
    const data = await Products.getPaginated(offset, limit)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const countProducts = async () => {
  try {
    const data = await Products.countData()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneProduct = async (id: number) => {
  try {
    const data = await Products.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchProducts = async (param: string) => {
  try {
    const data = await Products.searchData(param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateProducts = async (id: number, data: any) => {
  try {
    const response = await Products.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateManyProducts = async (paramId: string[], data: any[]) => {
  try {
    const response = await Products.updateManyData(paramId, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertProduct = async (data: ProductInterface[]) => {
  try {
    const response = await Products.insert(data)
    console.log(response)
    if (response != true) return response
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertManyProducts = async (data: ProductInterface[]) => {
  try {
    const response = await Products.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteProduct = async (id: number) => {
  try {
    const response = await Products.deleteData(id)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
