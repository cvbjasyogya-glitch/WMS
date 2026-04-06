import { ipcMain } from 'electron'
import {
  countInvoices,
  deleteInvoices,
  fetchAllInvoices,
  fetchByFieldInvoices,
  fetchLimitInvoices,
  fetchOneInvoices,
  filterTimeInvoice,
  insertInvoices,
  insertManyInvoices,
  searchInvoices,
  updateInvoices,
  updateManyInvoices
} from '../../../controller/invoiceController'
import { InvoiceInterface } from '../../../models/Invoices'

const prefix = 'invoices'

export const handleInvoices = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllInvoices()
    return response
  })

  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneInvoices(id)
    return response
  })

  ipcMain.handle(`${prefix}-get-by-field`, async (_, field: string, value: any) => {
    const response = await fetchByFieldInvoices(field, value)
    return response
  })

  ipcMain.handle(
    `${prefix}-get-paginated`,
    async (_, { page, limit, id, field, timeField, start, end }) => {
      const response = await fetchLimitInvoices(
        Number(page),
        Number(limit),
        Number(id),
        String(field),
        String(timeField),
        String(start),
        String(end)
      )
      return response
    }
  )

  ipcMain.handle(`${prefix}-search`, async (_, value: any) => {
    const response = await searchInvoices(value)
    return response
  })

  ipcMain.handle(`${prefix}-filter-time`, async (_, field: string, start: string, end: string) => {
    const response = await filterTimeInvoice(field, start, end)
    return response
  })

  ipcMain.handle(`${prefix}-count`, async (_, { id, field, timeField, start, end }) => {
    const response = await countInvoices(
      Number(id),
      String(field),
      String(timeField),
      String(start),
      String(end)
    )
    return response
  })

  ipcMain.handle(`${prefix}-insert`, async (_, data: InvoiceInterface) => {
    const response = await insertInvoices(data)
    return response
  })

  ipcMain.handle(`${prefix}-insert-many`, async (_, data: InvoiceInterface[]) => {
    const response = await insertManyInvoices(data)
    return response
  })

  ipcMain.handle(`${prefix}-update`, async (_, id: number, payload: any) => {
    const response = await updateInvoices(id, payload)
    return response
  })

  ipcMain.handle(`${prefix}-update-many`, async (_, paramId: string[], payload: any[]) => {
    const response = await updateManyInvoices(paramId, payload)
    return response
  })

  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const response = await deleteInvoices(id)
    return response
  })
}
