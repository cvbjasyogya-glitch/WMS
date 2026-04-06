import { ipcRenderer } from 'electron'
import { ConvertionInterface } from '../../models/Convertions'

const prefix = 'convertions'

export const convertionApi = {
  get: async (id?: number) => {
    if (id) {
      return await ipcRenderer.invoke(`${prefix}-get-one`, id)
    } else {
      return await ipcRenderer.invoke(`${prefix}-get-all`)
    }
  },
  getByField: async (field: string, value: any) => {
    return await ipcRenderer.invoke(`${prefix}-get-by-field`, field, value)
  },
  getByFields: async (field: string[], value: any) => {
    return await ipcRenderer.invoke(`${prefix}-get-by-fields`, field, value)
  },
  find: async (field: string[], value: any) => {
    return await ipcRenderer.invoke(`${prefix}-search`, field, value)
  },
  post: async (data: ConvertionInterface) => {
    return await ipcRenderer.invoke(`${prefix}-insert`, data)
  },
  postMany: async (data: ConvertionInterface) => {
    return await ipcRenderer.invoke(`${prefix}-insert-many`, data)
  },
  put: async (id: number, data: any) => {
    return await ipcRenderer.invoke(`${prefix}-update`, id, data)
  },
  putMany: async (paramId: string[], data: any) => {
    return await ipcRenderer.invoke(`${prefix}-update-many`, paramId, data)
  },
  delete: async (id: number) => {
    return await ipcRenderer.invoke(`${prefix}-delete`, id)
  }
}
