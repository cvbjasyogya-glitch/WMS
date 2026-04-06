import { ipcMain } from 'electron'
import { LoginResponse, loginUser } from '../../../controller/authController'

const prefix = 'auth'

export const handleAuth = () => {
  ipcMain.handle(
    `${prefix}-login`,
    async (_, data: { email: string; password: string }): Promise<LoginResponse> => {
      try {
        const response = await loginUser(data.email, data.password)
        return response
      } catch (error) {
        if (error instanceof Error) return { success: false, error: error.message }
        return { success: false, error: 'An unexpected error occurred' }
      }
    }
  )
}
