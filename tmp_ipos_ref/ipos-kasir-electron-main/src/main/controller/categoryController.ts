import CategoryModel from '../models/Categories'
import { db } from '../services/database/db_conn'
import { handleDatabaseError } from '../utils/error-handler'

const Categories = new CategoryModel(db)

export const fetchAllCategories = async () => {
  try {
    const data = await Categories.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneCategory = async (id: number) => {
  try {
    const data = await Categories.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchCategories = async (param: string) => {
  try {
    const data = await Categories.searchData(param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertCategory = async (data: { code: string; name: string }[]) => {
  try {
    const response = await Categories.insert(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertCategoryMany = async (data: { code: string; name: string }[]) => {
  try {
    const response = await Categories.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateCategories = async (id: number, data: any) => {
  try {
    const response = await Categories.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteCategory = async (id: number) => {
  try {
    const response = await Categories.deleteData(id)
    if (response != true) return { succes: false, error: response }
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
