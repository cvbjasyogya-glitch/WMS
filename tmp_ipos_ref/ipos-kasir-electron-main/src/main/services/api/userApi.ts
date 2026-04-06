import { ipcRenderer } from 'electron'

const prefix = 'users'

export const userApi = {
  get: async (id?: number) => {
    if (id) {
      return await ipcRenderer.invoke(`${prefix}-get-one`, id)
    } else {
      return await ipcRenderer.invoke(`${prefix}-get-all`)
    }
  },
  find: async (value: any) => {
    return await ipcRenderer.invoke(`${prefix}-search`, value)
  },
  post: async (data: any) => {
    return await ipcRenderer.invoke(`${prefix}-insert`, data)
  },
  put: async (id: number, data: any) => {
    return await ipcRenderer.invoke(`${prefix}-update`, id, data)
  },
  delete: async (id: number) => {
    return await ipcRenderer.invoke(`${prefix}-delete`, id)
  }
}
