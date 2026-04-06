import { ipcMain } from 'electron'
import {
  deleteUnit,
  fetchAllUnits,
  fetchOneUnit,
  insertManyUnit,
  insertUnit,
  updateUnit
} from '../../../controller/unitController'
import { UnitInterface } from '../../../models/Units'

const prefix = 'units'

export const handleUnits = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllUnits()
    return response
  })
  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneUnit(id)
    return response
  })
  ipcMain.handle(`${prefix}-insert`, async (_, data: UnitInterface[]) => {
    const response = await insertUnit(data)
    return response
  })
  ipcMain.handle(`${prefix}-insert-many`, async (_, data: UnitInterface[]) => {
    const response = await insertManyUnit(data)
    return response
  })
  ipcMain.handle(`${prefix}-update`, async (_, id: number, data: any) => {
    const response = await updateUnit(id, data)
    return response
  })
  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const repsonse = await deleteUnit(id)
    return repsonse
  })
}
