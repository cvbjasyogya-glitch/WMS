import { pick } from '../../renderer/src/utils/utils'
import UserModel, { ResponseData } from '../models/Users'
import { db } from '../services/database/db_conn'
import bcrypt from 'bcrypt'

const User = new UserModel(db)

export type LoginResponse =
  | { success: true; data: ResponseData }
  | { success: false; error: string }

export const loginUser = async (email: string, password: string): Promise<LoginResponse> => {
  try {
    const user = await User.getOneByField('email', email)
    if (!user) return { success: false, error: 'User not found' }

    const isPasswordValid = await bcrypt.compare(password, user[0].password)
    if (!isPasswordValid) return { success: false, error: 'Invalid password' }

    const data = pick(user[0], ['id', 'name', 'email', 'role_id'])
    return { success: true, data }
  } catch (error) {
    if (error instanceof Error) return { success: false, error: error.message }
    return { success: false, error: 'An unexpected error occurred' }
  }
}
