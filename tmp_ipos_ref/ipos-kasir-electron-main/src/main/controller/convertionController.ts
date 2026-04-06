import { db } from '../services/database/db_conn'
import ConvertionModel, { ConvertionInterface } from '../models/Convertions'
import { handleDatabaseError } from '../utils/error-handler'

const Convertions = new ConvertionModel(db)

export const fetchAllConvertions = async () => {
  try {
    const data = await Convertions.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneConvertions = async (id: number) => {
  try {
    const data = await Convertions.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchConvertionsByField = async (field: string, value: any) => {
  try {
    const data = await Convertions.findData(field, value)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchConvertionsByFields = async (field: string[], value: any) => {
  try {
    const data = await Convertions.findDataByFields(field, value)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchConvertions = async (field: string, param: string) => {
  try {
    const data = await Convertions.searchData(field, param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertConvertions = async (data: ConvertionInterface[]) => {
  try {
    const response = await Convertions.insert(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertManyConvertions = async (data: ConvertionInterface[]) => {
  try {
    const response = await Convertions.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateConvertions = async (id: number, data: any) => {
  try {
    const response = await Convertions.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateManyConvertions = async (paramId: string[], data: any[]) => {
  try {
    const response = await Convertions.updateManyData(paramId, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteConvertions = async (id: number) => {
  try {
    const response = await Convertions.deleteData(id)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
