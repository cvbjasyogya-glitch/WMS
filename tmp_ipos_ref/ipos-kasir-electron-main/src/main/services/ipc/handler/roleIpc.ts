import { ipcMain } from 'electron'
import { fetchAllRoles, fetchOneRole } from '../../../controller/roleController'

const prefix = 'roles'

export const handleRoles = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    return fetchAllRoles()
  })
  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    return fetchOneRole(id)
  })
  ipcMain.handle(`${prefix}-insert`, async () => {
    return ''
  })
  ipcMain.handle(`${prefix}-update`, async () => {
    return ''
  })
}
