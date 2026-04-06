import { ipcMain } from 'electron'
import {
  deleteCategory,
  fetchAllCategories,
  fetchOneCategory,
  insertCategory,
  insertCategoryMany,
  searchCategories,
  updateCategories
} from '../../../controller/categoryController'

const prefix = 'categories'

export const handleCategories = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllCategories()
    return response
  })
  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneCategory(id)
    return response
  })
  ipcMain.handle(`${prefix}-search`, async (_, value: any) => {
    const response = await searchCategories(value)
    return response
  })
  ipcMain.handle(`${prefix}-insert`, async (_, data: { code: string; name: string }[]) => {
    const response = await insertCategory(data)
    return response
  })
  ipcMain.handle(`${prefix}-insert-many`, async (_, data: { code: string; name: string }[]) => {
    const response = await insertCategoryMany(data)
    return response
  })
  ipcMain.handle(`${prefix}-update`, async (_, id: number, data: any) => {
    const response = await updateCategories(id, data)
    return response
  })
  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const repsonse = await deleteCategory(id)
    return repsonse
  })
}
