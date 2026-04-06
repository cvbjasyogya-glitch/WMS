import { ipcMain } from 'electron'

import {
  countInbounds,
  deleteInbounds,
  fetchAllInbounds,
  fetchLimitInbounds,
  fetchOneInbounds,
  filterTimeInbound,
  insertInbounds,
  insertManyInbounds,
  searchInbounds,
  updateInbounds,
  updateManyInbounds
} from '../../../controller/inboundController'
import { InboundInterface } from '../../../models/Inbounds'

const prefix = 'inbounds'

export const handleInbounds = () => {
  ipcMain.handle(`${prefix}-get-all`, async () => {
    const response = await fetchAllInbounds()
    return response
  })

  ipcMain.handle(`${prefix}-get-one`, async (_, id: number) => {
    const response = await fetchOneInbounds(id)
    return response
  })

  ipcMain.handle(
    `${prefix}-get-paginated`,
    async (_, { page, limit, id, field, timeField, start, end }) => {
      const response = await fetchLimitInbounds(
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
    const response = await searchInbounds(value)
    return response
  })

  ipcMain.handle(`${prefix}-filter-time`, async (_, field: string, start: string, end: string) => {
    const response = await filterTimeInbound(field, start, end)
    return response
  })

  ipcMain.handle(`${prefix}-count`, async (_, { id, field, timeField, start, end }) => {
    const response = await countInbounds(
      Number(id),
      String(field),
      String(timeField),
      String(start),
      String(end)
    )
    return response
  })

  ipcMain.handle(`${prefix}-insert`, async (_, data: InboundInterface) => {
    const response = await insertInbounds(data)
    return response
  })

  ipcMain.handle(`${prefix}-insert-many`, async (_, data: InboundInterface[]) => {
    const response = await insertManyInbounds(data)
    return response
  })

  ipcMain.handle(`${prefix}-update`, async (_, id: number, payload: any) => {
    const response = await updateInbounds(id, payload)
    return response
  })

  ipcMain.handle(`${prefix}-update-many`, async (_, paramId: string[], payload: any[]) => {
    const response = await updateManyInbounds(paramId, payload)
    return response
  })

  ipcMain.handle(`${prefix}-delete`, async (_, id: number) => {
    const response = await deleteInbounds(id)
    return response
  })
}
