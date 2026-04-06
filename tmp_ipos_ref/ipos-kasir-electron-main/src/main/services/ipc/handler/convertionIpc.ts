import { ipcMain } from 'electron'
import {
  deleteConvertions,
  fetchAllConvertions,
  fetchOneConvertions,
  searchConvertions,
  insertConvertions,
  fetchConvertionsByField,
  updateConvertions,
  insertManyConvertions,
  updateManyConvertions,
  fetchConvertionsByFields
} from '../../../controller/convertionController'
import { ConvertionInterface } from '../../../models/Convertions'

const prefix = 'convertions'

export const handleConvertions = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllConvertions()
    return response
  })

  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneConvertions(id)
    return response
  })

  ipcMain.handle(`${prefix}-get-by-field`, async (_, field: string, value: any) => {
    const response = await fetchConvertionsByField(field, value)
    return response
  })

  ipcMain.handle(`${prefix}-get-by-fields`, async (_, field: string[], value: any) => {
    const response = await fetchConvertionsByFields(field, value)
    return response
  })

  ipcMain.handle(`${prefix}-search`, async (_, field: string, value: any) => {
    console.log(field)
    const response = await searchConvertions(field, value)
    return response
  })

  ipcMain.handle(`${prefix}-insert`, async (_, data: ConvertionInterface[]) => {
    const response = await insertConvertions(data)
    return response
  })

  ipcMain.handle(`${prefix}-insert-many`, async (_, data: ConvertionInterface[]) => {
    const response = await insertManyConvertions(data)
    return response
  })

  ipcMain.handle(`${prefix}-update`, async (_, id: number, payload: any) => {
    const response = await updateConvertions(id, payload)
    return response
  })

  ipcMain.handle(`${prefix}-update-many`, async (_, paramId: string[], payload: any) => {
    const response = await updateManyConvertions(paramId, payload)
    return response
  })

  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const response = await deleteConvertions(id)
    return response
  })
}
