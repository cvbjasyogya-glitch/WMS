export const handleCtrlF = (event: KeyboardEvent, inputRef: React.RefObject<HTMLInputElement>) => {
  if (event.ctrlKey && event.key === 'f') {
    event.preventDefault()
    if (document.activeElement === inputRef.current) {
      inputRef.current?.blur()
    } else {
      inputRef.current?.focus()
    }
  }
}

export const handleCtrlE = (
  event: KeyboardEvent,
  setIsEdit: React.Dispatch<React.SetStateAction<boolean>>
) => {
  if (event.ctrlKey && event.key === 'e') {
    event.preventDefault()
    setIsEdit(true)
  }
}

export const handleCtrlT = (event: KeyboardEvent, func: () => void) => {
  if (event.ctrlKey && event.key === 't') {
    event.preventDefault()
    func()
  }
}

export const handleEsc = (event: KeyboardEvent, func: () => void) => {
  if (event.key === 'Escape') {
    event.preventDefault()
    func()
  }
}
