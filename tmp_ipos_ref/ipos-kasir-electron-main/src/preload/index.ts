import { contextBridge } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'
import {
  authApi,
  categoryApi,
  customerApi,
  discountApi,
  inboundApi,
  productApi,
  roleApi,
  unitApi,
  userApi,
  invoiceApi,
  transactionApi
} from '../main/services/api'
import { convertionApi } from '../main/services/api/convertionApi'

// Custom APIs for renderer
const api = {
  auth: authApi,
  user: userApi,
  product: productApi,
  unit: unitApi,
  convertion: convertionApi,
  discount: discountApi,
  roleApi: roleApi,
  customer: customerApi,
  inbound: inboundApi,
  invoice: invoiceApi,
  transaction: transactionApi,
  category: categoryApi
}
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error('Failed to expose APIs:', error)
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI
  // @ts-ignore (define in dts)
  window.api = api
}
