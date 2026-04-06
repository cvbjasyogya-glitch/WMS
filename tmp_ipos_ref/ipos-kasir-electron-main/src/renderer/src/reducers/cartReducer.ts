import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { generateProductCode } from '../utils/utils'

interface Conversion {
  id: number
  sell_price: number
  units_name: string
  stock: number
  grosir: number | null
  grosir_price: number | null
}

interface CartItem {
  cartId: string
  id: number
  name: string
  quantity: number | null
  conversions: Conversion[]
  selectedConversionId?: number | null
  sell_price?: number | null
  normal_price?: number | null
  purchase_price?: number | null
  stock?: number
  conversionName?: string | null
  is_stock_variant?: number
  discount_id?: number
  tax_id?: number
}

interface CartState {
  items: CartItem[]
}

const initialState: CartState = {
  items: []
}

const cartSlice = createSlice({
  name: 'cart',
  initialState,
  reducers: {
    addToCart(state, action: PayloadAction<CartItem>) {
      state.items.push({ ...action.payload, quantity: 1, cartId: generateProductCode() })
    },
    removeFromCart(state, action: PayloadAction<string>) {
      state.items = state.items.filter((item) => item.cartId !== action.payload)
    },
    clearCart(state) {
      state.items = []
    },
    setSelectedConversion(
      state,
      action: PayloadAction<{
        id: number
        conversionId: number | null
        conversionName: string | null
        sell_price: number | null
        cartId: string
      }>
    ) {
      const existingItem = state.items.find((item) => item.cartId === action.payload.cartId)
      if (existingItem) {
        const conversion = existingItem.conversions.find(
          (conversion) => conversion.id === action.payload.conversionId
        )

        if (conversion) {
          const grosir = conversion.grosir
          const quantity = existingItem.quantity

          if (quantity != null && grosir != null && quantity >= grosir) {
            existingItem.sell_price = conversion.grosir_price
          } else {
            existingItem.sell_price = action.payload.sell_price
          }
        }

        existingItem.normal_price = action.payload.sell_price
        existingItem.selectedConversionId = action.payload.conversionId
        existingItem.conversionName = action.payload.conversionName
      }
    },
    setQuantity(state, action: PayloadAction<{ cartId: string; qty: number | null }>) {
      const existingItem = state.items.find((item) => item.cartId === action.payload.cartId)
      if (existingItem) {
        existingItem.quantity = action.payload.qty
        const conversion = existingItem.conversions.find(
          (conversion) => conversion.id === existingItem.selectedConversionId
        )

        if (conversion) {
          const grosir = conversion.grosir
          const quantity = existingItem.quantity

          if (quantity != null && grosir != null && quantity >= grosir) {
            existingItem.sell_price = conversion.grosir_price
          } else {
            existingItem.sell_price = existingItem.normal_price
          }
        }
      }
    }
  }
})

export const { addToCart, removeFromCart, clearCart, setQuantity, setSelectedConversion } =
  cartSlice.actions
export default cartSlice.reducer
export type { CartState }
