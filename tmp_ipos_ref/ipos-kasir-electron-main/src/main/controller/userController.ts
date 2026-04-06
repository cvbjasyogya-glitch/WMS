import UserModel from '../models/Users'
import { db } from '../services/database/db_conn'

const User = new UserModel(db)

export const insertUser = async (data: any) => {
  try {
    await User.insert(data)
    return { success: true }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const getAllUsers = async () => {
  try {
    const users = await User.getAll()
    return users
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const getOneUser = async (id: number) => {
  try {
    const user = await User.getOne(id)
    return user
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}

export const getOneUserByField = async (field: string, value: any) => {
  try {
    const user = await User.getOneByField(field, value)
    return user
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
