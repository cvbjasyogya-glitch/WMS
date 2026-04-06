const { ipcRenderer } = window.require('electron')

export const sendToMain = (message: any) => {
  ipcRenderer.send('message-from-renderer', message)
}

export const printInvoice = (invoice: any) => {
  ipcRenderer.send('print', invoice)

  ipcRenderer.once('print-file', (_, printFilePath) => {
    console.log('Print file received:', printFilePath)
    ipcRenderer.send('print-file-reply', printFilePath)
  })
}
