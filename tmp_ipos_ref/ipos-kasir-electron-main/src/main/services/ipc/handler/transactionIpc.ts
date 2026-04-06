import { ipcMain } from 'electron'
import {
  countTransactions,
  deleteTransactions,
  fetchAllTransactions,
  fetchByFieldTransactions,
  fetchLimitTransactions,
  fetchOneTransactions,
  filterTimeTransactions,
  insertManyTransactions,
  insertTransactions,
  searchTransactions,
  updateManyTransactions,
  updateTransactions
} from '../../../controller/transactionController'
import { TransactionInterface } from '../../../models/Transactions'

const prefix = 'transactions'

export const handleTransactions = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllTransactions()
    return response
  })

  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneTransactions(id)
    return response
  })

  ipcMain.handle(`${prefix}-get-by-field`, async (_, field: string, value: any) => {
    const response = await fetchByFieldTransactions(field, value)
    return response
  })

  ipcMain.handle(
    `${prefix}-get-paginated`,
    async (_, { page, limit, id, field, timeField, start, end }) => {
      const response = await fetchLimitTransactions(
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
    const response = await searchTransactions(value)
    return response
  })

  ipcMain.handle(`${prefix}-filter-time`, async (_, field: string, start: string, end: string) => {
    const response = await filterTimeTransactions(field, start, end)
    return response
  })

  ipcMain.handle(`${prefix}-count`, async (_, { id, field, timeField, start, end }) => {
    const response = await countTransactions(
      Number(id),
      String(field),
      String(timeField),
      String(start),
      String(end)
    )
    return response
  })

  ipcMain.handle(`${prefix}-insert`, async (_, data: TransactionInterface) => {
    const response = await insertTransactions(data)
    return response
  })

  ipcMain.handle(`${prefix}-insert-many`, async (_, data: TransactionInterface[]) => {
    const response = await insertManyTransactions(data)
    return response
  })

  ipcMain.handle(`${prefix}-update`, async (_, id: number, payload: any) => {
    const response = await updateTransactions(id, payload)
    return response
  })

  ipcMain.handle(`${prefix}-update-many`, async (_, paramId: string[], payload: any[]) => {
    const response = await updateManyTransactions(paramId, payload)
    return response
  })

  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const response = await deleteTransactions(id)
    return response
  })
}
