// electron.d.ts
import 'electron'

declare global {
  interface CommonAPI {
    get(id: number): Promise<{ success: boolean; data?: any; error?: string }>
    post(data: any): Promise<{ success: boolean; data?: any; error?: string }>
    delete(data: any): Promise<{ success: boolean; data?: any; error?: string }>
  }

  interface AuthAPI {
    login(payload: {
      email: string
      password: string
    }): Promise<{ success: boolean; data?: any; error?: string }>
  }

  interface API {
    auth: AuthAPI
    user: CommonAPI
    product: CommonAPI
    category: CommonAPI
    convertion: CommonAPI
    discount: CommonAPI
    unit: CommonAPI
    invoice: CommonAPI
    transaction: CommonAPI
    inbound: CommonAPI
  }

  interface Window {
    electron: {
      ipcRenderer: {
        send: (channel: string, ...args: any[]) => void
        invoke: (channel: string, ...args: any[]) => Promise<any>
      }
      process: {
        versions: any
      }
    }
    api: API // Use the structured API type
  }
}
