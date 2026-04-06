import UnitModel, { UnitInterface } from '../models/Units'
import { db } from '../services/database/db_conn'
import { handleDatabaseError } from '../utils/error-handler'

const Units = new UnitModel(db)

export const fetchAllUnits = async () => {
  try {
    const data = await Units.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneUnit = async (id: number) => {
  try {
    const data = await Units.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertUnit = async (data: UnitInterface[]) => {
  try {
    const response = await Units.insert(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertManyUnit = async (data: UnitInterface[]) => {
  try {
    const response = await Units.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateUnit = async (id: number, data: any) => {
  try {
    const response = await Units.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteUnit = async (id: number) => {
  try {
    const response = await Units.deleteData(id)
    if (response != true) return { succes: false, error: response }
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
