import { configureStore } from '@reduxjs/toolkit'
import { cartReducer, tableReducer, tabReducer } from '../reducers'

const store = configureStore({
  reducer: {
    table: tableReducer,
    tab: tabReducer,
    cart: cartReducer
  }
})

export type RootState = ReturnType<typeof store.getState>

export default store
