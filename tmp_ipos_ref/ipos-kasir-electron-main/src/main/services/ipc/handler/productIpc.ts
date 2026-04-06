import { ipcMain } from 'electron'
import {
  deleteProduct,
  fetchAllProducts,
  fetchOneProduct,
  searchProducts,
  insertProduct,
  updateProducts,
  fetchLimitProducts,
  countProducts,
  insertManyProducts,
  updateManyProducts
} from '../../../controller/productController'
import { ProductInterface } from '../../../models/Products'

const prefix = 'products'

export const handleProducts = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllProducts()
    return response
  })

  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneProduct(id)
    return response
  })

  ipcMain.handle(`${prefix}-get-paginated`, async (_, { page, limit }) => {
    const response = await fetchLimitProducts(Number(page), Number(limit))
    return response
  })

  ipcMain.handle(`${prefix}-search`, async (_, value: any) => {
    const response = await searchProducts(value)
    return response
  })

  ipcMain.handle(`${prefix}-count`, async (_) => {
    const response = await countProducts()
    return response
  })

  ipcMain.handle(`${prefix}-insert`, async (_, data: ProductInterface[]) => {
    const response = await insertProduct(data)
    return response
  })

  ipcMain.handle(`${prefix}-insert-many`, async (_, data: ProductInterface[]) => {
    const response = await insertManyProducts(data)
    return response
  })

  ipcMain.handle(`${prefix}-update`, async (_, id: number, payload: any) => {
    const response = await updateProducts(id, payload)
    return response
  })

  ipcMain.handle(`${prefix}-update-many`, async (_, paramId: string[], payload: any[]) => {
    const response = await updateManyProducts(paramId, payload)
    return response
  })

  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const response = await deleteProduct(id)
    return response
  })
}
