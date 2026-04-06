import { db } from '../services/database/db_conn'
import DiscountsModels, { DiscountInterface } from '../models/Discounts'
import { handleDatabaseError } from '../utils/error-handler'

const Discounts = new DiscountsModels(db)

export const fetchAllDiscounts = async () => {
  try {
    const data = await Discounts.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneDiscounts = async (id: number) => {
  try {
    const data = await Discounts.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchDiscounts = async (param: string) => {
  try {
    const data = await Discounts.searchData(param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertDiscounts = async (data: DiscountInterface[]) => {
  try {
    const response = await Discounts.insert(data)
    console.log(response)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteDiscounts = async (id: number) => {
  try {
    const response = await Discounts.deleteData(id)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
