import { ipcRenderer } from 'electron'

const prefix = 'products'

export const productApi = {
  get: async (id?: number) => {
    if (id) {
      return await ipcRenderer.invoke(`${prefix}-get-one`, id)
    } else {
      return await ipcRenderer.invoke(`${prefix}-get-all`)
    }
  },
  getPaginated: async (page: number, limit: number) => {
    return await ipcRenderer.invoke(`${prefix}-get-paginated`, { page, limit })
  },
  count: async () => {
    return await ipcRenderer.invoke(`${prefix}-count`)
  },
  find: async (value: any) => {
    return await ipcRenderer.invoke(`${prefix}-search`, value)
  },
  post: async (data: any) => {
    return await ipcRenderer.invoke(`${prefix}-insert`, data)
  },
  postMany: async (data: any) => {
    return await ipcRenderer.invoke(`${prefix}-insert-many`, data)
  },
  put: async (id: number, data: any) => {
    return await ipcRenderer.invoke(`${prefix}-update`, id, data)
  },
  putMany: async (paramId: string[], data: any[]) => {
    return await ipcRenderer.invoke(`${prefix}-update-many`, paramId, data)
  },
  delete: async (id: number) => {
    return await ipcRenderer.invoke(`${prefix}-delete`, id)
  }
}
