import InboundModel, { InboundInterface } from '../models/Inbounds'
import { db } from '../services/database/db_conn'
import { handleDatabaseError } from '../utils/error-handler'

const Inbounds = new InboundModel(db)

export const fetchAllInbounds = async () => {
  try {
    const data = await Inbounds.getAll()
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchLimitInbounds = async (
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
    const data = await Inbounds.getPaginated(offset, limit, id, field, timeField, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const countInbounds = async (
  id?: number,
  field?: string,
  timeField?: string,
  start?: string,
  end?: string
) => {
  try {
    const data = await Inbounds.countData(id, field, timeField, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneInbounds = async (id: number) => {
  try {
    const data = await Inbounds.getOne(id)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const searchInbounds = async (param: string) => {
  try {
    const data = await Inbounds.searchData(param)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const filterTimeInbound = async (field: string, start: string, end: string) => {
  try {
    const data = await Inbounds.filterDataTime(field, start, end)
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateInbounds = async (id: number, data: any) => {
  try {
    const response = await Inbounds.updateData(id, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const updateManyInbounds = async (paramId: string[], data: any[]) => {
  try {
    const response = await Inbounds.updateManyData(paramId, data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertInbounds = async (data: InboundInterface) => {
  try {
    const response = await Inbounds.insert(data)
    console.log(response)
    if (response != true) return response
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const insertManyInbounds = async (data: InboundInterface[]) => {
  try {
    const response = await Inbounds.insertMany(data)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const deleteInbounds = async (id: number) => {
  try {
    const response = await Inbounds.deleteData(id)
    if (response != true) return handleDatabaseError(response)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
