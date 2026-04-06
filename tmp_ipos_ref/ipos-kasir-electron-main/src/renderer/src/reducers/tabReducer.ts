import { createSlice } from '@reduxjs/toolkit'

const tabSlice = createSlice({
  name: 'tab',
  initialState: {
    tabIdx: 0
  },
  reducers: {
    setTabIdx: (state, action) => {
      state.tabIdx = action.payload
    }
  }
})

export const { setTabIdx } = tabSlice.actions

export default tabSlice.reducer
