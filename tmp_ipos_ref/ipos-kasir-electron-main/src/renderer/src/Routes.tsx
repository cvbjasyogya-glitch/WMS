import { Route, Routes } from 'react-router-dom'
import { LoginPage } from './pages/login/page'
import { DashboardPage } from './pages/dashboard/page'
import { MasterPage } from './pages/master/page'
import { ProductPage } from './pages/product/page'
import { PointPage } from './pages/point/page'
import { TransactionPage } from './pages/invoice/page'
import { MasterUnit } from './pages/master/unit/page'
import { MasterStock } from './pages/master/stock/page'
import { MasterPrice } from './pages/master/price/page'
import { MasterCategory } from './pages/master/category/page'
import { AddProduct } from './pages/window/AddProduct'
import { MasterDiscount } from './pages/master/discount/page'
import { AddStock } from './pages/window/AddStock'
import { PaymentPage } from './pages/payment/page'
import { AddCustomer } from './pages/window/AddCustomer'
import { InboundPage } from './pages/inbound/page'
import { ImportMaster } from './pages/window/ImportMaster'
import { ImportStock } from './pages/window/ImportStock'
import { OutboundPage } from './pages/outbound/page'
import { PrintPage } from './pages/window/Print'
import { ImportPrice } from './pages/window/ImportPrice'
import { ImportCustomer } from './pages/window/ImportCustomer'

export default function Routing() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/master" element={<MasterPage />} />
      <Route path="/master/unit" element={<MasterUnit />} />
      <Route path="/master/stock" element={<MasterStock />} />
      <Route path="/master/price" element={<MasterPrice />} />
      <Route path="/master/category" element={<MasterCategory />} />
      <Route path="/master/discount" element={<MasterDiscount />} />
      <Route path="/master/add-product" element={<AddProduct />} />
      <Route path="/master/import" element={<ImportMaster />} />
      <Route path="/master/import-stock" element={<ImportStock />} />
      <Route path="/master/import-price" element={<ImportPrice />} />
      <Route path="/point/add-customer" element={<AddCustomer />} />
      <Route path="/point/import-customer" element={<ImportCustomer />} />
      <Route path="/master/add-stock/:id" element={<AddStock />} />
      <Route path="/product" element={<ProductPage />} />
      <Route path="/point" element={<PointPage />} />
      <Route path="/inbound" element={<InboundPage />} />
      <Route path="/outbound" element={<OutboundPage />} />
      <Route path="/transaction" element={<TransactionPage />} />
      <Route path="/payment" element={<PaymentPage />} />
      <Route path="/print/:id" element={<PrintPage />} />
    </Routes>
  )
}
