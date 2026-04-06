import { ipcMain } from 'electron'
import {
  getAllUsers,
  getOneUser,
  getOneUserByField,
  insertUser
} from '../../../controller/userController'

const prefix = 'users'

export const handleUsers = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    return await getAllUsers()
  })
  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    return await getOneUser(id)
  })
  ipcMain.handle(`${prefix}-get-one-by-fields`, async (_, field: string, value: any) => {
    return await getOneUserByField(field, value)
  })
  ipcMain.handle(`${prefix}-insert`, async (_, data) => {
    return await insertUser(data)
  })
  ipcMain.handle(`${prefix}-update`, async (_, user) => {
    return 'update' + user
  })
}
