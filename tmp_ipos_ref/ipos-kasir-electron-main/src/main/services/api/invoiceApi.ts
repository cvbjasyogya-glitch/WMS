import { ipcRenderer } from 'electron'
import { InvoiceInterface } from '../../models/Invoices'

const prefix = 'invoices'

export const invoiceApi = {
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
  getPaginated: async (
    page: number,
    limit: number,
    id?: number,
    field?: string,
    timeField?: string,
    start?: string,
    end?: string
  ) => {
    return await ipcRenderer.invoke(`${prefix}-get-paginated`, {
      page,
      limit,
      id,
      field,
      timeField,
      start,
      end
    })
  },
  count: async (id?: number, field?: string, timeField?: string, start?: string, end?: string) => {
    return await ipcRenderer.invoke(`${prefix}-count`, {
      id,
      field,
      timeField,
      start,
      end
    })
  },
  find: async (value: any) => {
    return await ipcRenderer.invoke(`${prefix}-search`, value)
  },
  filterTime: async (field: string, start: string, end: string) => {
    return await ipcRenderer.invoke(`${prefix}-filter-time`, field, start, end)
  },
  post: async (data: InvoiceInterface) => {
    return await ipcRenderer.invoke(`${prefix}-insert`, data)
  },
  postMany: async (data: InvoiceInterface[]) => {
    return await ipcRenderer.invoke(`${prefix}-insert-many`, data)
  },
  put: async (id: number, data: any) => {
    return await ipcRenderer.invoke(`${prefix}-update`, id, data)
  },
  putMany: async (paramId: string, data: any[]) => {
    return await ipcRenderer.invoke(`${prefix}-update-many`, paramId, data)
  },
  delete: async (id: number) => {
    return await ipcRenderer.invoke(`${prefix}-delete`, id)
  }
}
