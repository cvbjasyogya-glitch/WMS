import { ipcMain } from 'electron'
import {
  deleteCustomers,
  fetchAllCustomers,
  fetchOneCustomers,
  insertCustomers,
  insertManyCustomers,
  searchCustomers,
  updateCustomers
} from '../../../controller/customerController'
import { CustomerInterface } from '../../../models/Customers'

const prefix = 'customers'

export const handleCustomers = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    return await fetchAllCustomers()
  })
  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    return await fetchOneCustomers(id)
  })
  ipcMain.handle(`${prefix}-insert`, async (_, data: CustomerInterface) => {
    return await insertCustomers(data)
  })
  ipcMain.handle(`${prefix}-insert-many`, async (_, data: CustomerInterface[]) => {
    return await insertManyCustomers(data)
  })
  ipcMain.handle(`${prefix}-update`, async (_, id: number, data: any) => {
    return await updateCustomers(id, data)
  })
  ipcMain.handle(`${prefix}-search`, async (_, value: any) => {
    const response = await searchCustomers(value)
    return response
  })
  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    return await deleteCustomers(id)
  })
}
