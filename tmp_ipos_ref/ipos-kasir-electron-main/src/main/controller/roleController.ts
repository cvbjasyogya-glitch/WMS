import RoleModel from '../models/Roles'
import { db } from '../services/database/db_conn'

const Role = new RoleModel(db)

export const insertUser = async (data: any) => {
  try {
    await Role.insert(data)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchAllRoles = async () => {
  try {
    const roles = await Role.getAll()
    return roles
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const fetchOneRole = async (id: number) => {
  try {
    const role = await Role.getOne(id)
    return role
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
