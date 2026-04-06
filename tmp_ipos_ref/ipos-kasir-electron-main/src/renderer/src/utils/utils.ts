import { ClassValue, clsx } from 'clsx'
import { NavigateFunction } from 'react-router-dom'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function getCurrentTimestamp(): string {
  const now = new Date()
  return now.toISOString()
}

export function pick<T extends Record<string, any>, K extends keyof T>(
  obj: T,
  keys: K[]
): Pick<T, K> {
  return keys.reduce(
    (result, key) => {
      if (key in obj) {
        result[key] = obj[key]
      }
      return result
    },
    {} as Pick<T, K>
  )
}

export const handleKeyDown = (
  event: KeyboardEvent,
  setIsEdit: React.Dispatch<React.SetStateAction<boolean>>,
  navigate: NavigateFunction,
  inputRef: React.RefObject<HTMLInputElement>
) => {
  switch (true) {
    case event.ctrlKey && event.key.toLowerCase() === 'e':
      event.preventDefault()
      setIsEdit(true)
      break
    case event.ctrlKey && event.key.toLowerCase() === 'f':
      event.preventDefault()
      if (document.activeElement === inputRef.current) {
        inputRef.current?.blur()
      } else {
        inputRef.current?.focus()
      }
      break
    case event.ctrlKey && event.key.toLowerCase() === 't':
      event.preventDefault()
      navigate('/master/add-product')
      break
    case event.key === 'Escape':
      setIsEdit(false)
      break
    default:
      break
  }
}

export const formatToIDR = (number: number): string => {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR' }).format(number)
}

export function generateProductCode() {
  let code = ''
  for (let i = 0; i < 12; i++) {
    code += Math.floor(Math.random() * 10).toString()
  }
  return code
}

export const now = function () {
  const nowUtc = new Date()

  const jakartaOffset = 7 * 60 * 60 * 1000
  const jakartaDate = new Date(nowUtc.getTime() + jakartaOffset)

  const year = jakartaDate.getUTCFullYear()
  const month = String(jakartaDate.getUTCMonth() + 1).padStart(2, '0')
  const day = String(jakartaDate.getUTCDate()).padStart(2, '0')
  const hours = String(jakartaDate.getUTCHours()).padStart(2, '0')
  const minutes = String(jakartaDate.getUTCMinutes()).padStart(2, '0')
  const seconds = String(jakartaDate.getUTCSeconds()).padStart(2, '0')

  const formattedDate = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`

  return formattedDate
}
