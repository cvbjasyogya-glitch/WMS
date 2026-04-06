import { jwtDecode } from 'jwt-decode'
import Cookies from 'universal-cookie'

export interface DecodedToken {
  phone?: string
  user_metadata: any
  email?: string
  sub?: string
}

export interface UserData extends Partial<DecodedToken> {
  id?: string
}

export const getToken = (): string =>
  document.cookie
    .split('; ')
    .find((row) => row.startsWith('access_token='))
    ?.split('=')[1] || ''

export const getRolesFromToken = (token: string | null): string | null => {
  if (!token) return null
  try {
    const decoded = jwtDecode<DecodedToken>(token)
    return decoded.user_metadata.role
  } catch (error) {
    console.error('Token decoding failed:', error)
    return null
  }
}

export const getDatasFromToken = (token: string): UserData | null => {
  if (!token) return null
  try {
    const decoded = jwtDecode<DecodedToken>(token)
    console.log(decoded)
    return {
      id: decoded.sub,
      email: decoded.email,
      phone: decoded.phone
    }
  } catch (error) {
    console.error('Token decoding failed:', error)
    return null
  }
}

export const storeCookie = (token: string) => {
  const cookies = new Cookies()
  cookies.set('access_token', token, {
    path: '/',
    secure: true
  })
}

export const removeCookie = () => {
  const cookies = new Cookies()
  cookies.remove('access_token')
}
