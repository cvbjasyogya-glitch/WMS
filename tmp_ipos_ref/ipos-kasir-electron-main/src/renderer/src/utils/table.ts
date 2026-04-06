// useTableKeyboardNavigation.ts
import { useEffect } from 'react'

const useTableKeyboardNavigation = ({ isEdit, setFocusedCell, onDelete, datas }: any) => {
  const handleKeyDown = (event: KeyboardEvent) => {
    if (!isEdit) return

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        setFocusedCell((prev) => {
          const newIndex = Math.min((prev ?? 0) + 1, (datas.length || 0) - 1)
          return newIndex
        })
        break

      case 'ArrowUp':
        event.preventDefault()
        setFocusedCell((prev) => {
          const newIndex = Math.max((prev ?? 0) - 1, 0)
          return newIndex
        })
        break

      case 'Escape':
        event.preventDefault()
        setFocusedCell(null)
        break

      case 'Delete':
        event.preventDefault()
        setFocusedCell((prev) => {
          if (prev !== null && datas[prev]) {
            onDelete(datas[prev].id)
            return prev > 0 ? prev - 1 : null
          }
          return prev
        })
        break

      default:
        break
    }
  }

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isEdit, datas])
}

export default useTableKeyboardNavigation
