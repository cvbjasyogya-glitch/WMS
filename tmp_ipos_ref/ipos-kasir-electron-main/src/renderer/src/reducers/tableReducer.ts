import { createSlice, PayloadAction } from '@reduxjs/toolkit'

export interface TableState<T> {
  data: T[]
  highlightedIndex: number
  isQuery: boolean
}

const initialState: TableState<any> = {
  data: [],
  highlightedIndex: -1,
  isQuery: false
}

const tableSlice = createSlice({
  name: 'table',
  initialState,
  reducers: {
    setData(state, action: PayloadAction<any[]>) {
      state.data = action.payload
    },
    setHighlightedIndex(state, action: PayloadAction<number>) {
      state.highlightedIndex = action.payload
    },
    setIsQuery(state, action: PayloadAction<boolean>) {
      state.isQuery = action.payload
    },
    clearData(state) {
      state.data = []
      state.highlightedIndex = -1
      state.isQuery = false
    }
  }
})

export const { setData, setHighlightedIndex, setIsQuery, clearData } = tableSlice.actions
export default tableSlice.reducer
