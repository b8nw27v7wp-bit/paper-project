import { contextBridge, ipcRenderer } from 'electron'

// P0: minimal bridge, mirrors docs 02-架构设计 §4.1 + 05-API §4
// 通道: window.electronBridge.invoke(method, payload)
const bridge = {
  invoke: (channel: string, data?: unknown) => ipcRenderer.invoke(channel, data),
  on: (channel: string, callback: (...args: unknown[]) => void) => {
    const sub = (_: unknown, ...args: unknown[]) => callback(...args)
    ipcRenderer.on(channel, sub)
    return () => ipcRenderer.removeListener(channel, sub)
  },
  // health check shortcut
  health: () => ipcRenderer.invoke('app:health'),
  getVersion: () => ipcRenderer.invoke('app:version'),
}

contextBridge.exposeInMainWorld('electronBridge', bridge)

declare global {
  interface Window {
    electronBridge: typeof bridge
  }
}
