import IpcProvider from './provider'
import {
  handleAuth,
  handleCategories,
  handleConvertions,
  handleCustomers,
  handleInvoices,
  handleProducts,
  handleRoles,
  handleUnits,
  handleUsers
} from './handler'
import { handleDiscounts } from './handler/discountIpc'
import { handleInbounds } from './handler/inboundIpc'
import { handleTransactions } from './handler/transactionIpc'

const ipc = new IpcProvider()
ipc.registerHandler([
  handleUsers,
  handleProducts,
  handleRoles,
  handleCategories,
  handleCustomers,
  handleUnits,
  handleConvertions,
  handleDiscounts,
  handleAuth,
  handleInvoices,
  handleTransactions,
  handleInbounds
])

export { ipc }
