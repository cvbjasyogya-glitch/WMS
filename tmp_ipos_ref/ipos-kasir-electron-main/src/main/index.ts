import { app, BrowserWindow, ipcMain } from 'electron'
import path, { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { connectDB } from './services/database/db_conn'
import { ipc } from './services/ipc'
import { PosPrinter } from '@plick/electron-pos-printer'
import { printdata } from './utils/printData'

require('@electron/remote/main').initialize()

let mainWindow: BrowserWindow | null = null // Declare mainWindow at a higher scope
let childWindow: BrowserWindow | null = null
const appIcon = path.join(__dirname, '../../resources/icon.ico')
const options: any = {
  preview: false,
  margin: '0 0 0 0',
  copies: 1,
  printerName: 'Kasir Toko',
  timeOutPerLine: 400,
  pageSize: '80mm'
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1080,
    height: 720,
    show: false,
    icon: appIcon,
    autoHideMenuBar: true,
    fullscreen: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    childWindow = new BrowserWindow({
      width: 800,
      height: 600,
      autoHideMenuBar: true,
      frame: false,
      webPreferences: {
        preload: join(__dirname, '../preload/index.js'),
        contextIsolation: true,
        sandbox: false
      }
    })

    childWindow.loadURL(url)

    childWindow.on('closed', () => {
      childWindow = null
    })

    return {
      action: 'deny'
    }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null // Ensure cleanup
  })
}

app.whenReady().then(() => {
  electronApp.setAppUserModelId('com.electron')

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // IPC event to close the main window
  ipcMain.on('close-me', () => {
    if (mainWindow) {
      console.log('Closing the main window...')
      mainWindow.close()
    }
  })

  ipcMain.on('print', (_, cash, invoice) => {
    const printData = printdata(cash, invoice)
    PosPrinter.print(printData, options)
      .then(console.log)
      .catch((error) => {
        console.error(error)
      })
  })

  connectDB().then(() => {
    createWindow()
    ipc.setupHandler()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
