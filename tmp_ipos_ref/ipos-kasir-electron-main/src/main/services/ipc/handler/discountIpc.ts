import { ipcMain } from 'electron'
import { DiscountInterface } from '../../../models/Discounts'
import {
  deleteDiscounts,
  fetchAllDiscounts,
  fetchOneDiscounts,
  insertDiscounts,
  searchDiscounts
} from '../../../controller/discountController'

const prefix = 'discounts'

export const handleDiscounts = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllDiscounts()
    return response
  })

  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneDiscounts(id)
    return response
  })

  ipcMain.handle(`${prefix}-search`, async (_, value: any) => {
    const response = await searchDiscounts(value)
    return response
  })

  ipcMain.handle(`${prefix}-insert`, async (_, data: DiscountInterface[]) => {
    const response = await insertDiscounts(data)
    return response
  })

  ipcMain.handle(`${prefix}-update`, async () => {
    return ''
  })

  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const response = await deleteDiscounts(id)
    return response
  })
}
