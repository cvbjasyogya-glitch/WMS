import { ipcRenderer } from 'electron'

const prefix = 'auth'

export const authApi = {
  login: async (data: any) => {
    const response = await ipcRenderer.invoke(`${prefix}-login`, data)
    return response
  }
}
