class IpcProvider {
  private registeredHandlers: Array<string> = []

  public registerHandler(handlers: Array<() => void>) {
    handlers.forEach((handler) => {
      handler()
      this.registeredHandlers.push(handler.name)
    })
  }

  public setupHandler(): Array<string> {
    return this.registeredHandlers
  }
}

export default IpcProvider
