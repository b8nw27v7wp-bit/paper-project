import { contextBridge, ipcRenderer } from 'electron'

// P2 W17-22：preload contextBridge 完整暴露，对齐 02-架构 §4.1 + 05-API §4
// 通道全量：app:health/window:*/store:*/notify*/desktop:sync，隔离渲染进程
const bridge = {
  // 通用
  invoke: (channel: string, data?: unknown) => ipcRenderer.invoke(channel, data),
  on: (channel: string, callback: (...args: unknown[]) => void) => {
    const sub = (_: unknown, ...args: unknown[]) => callback(...args)
    ipcRenderer.on(channel, sub)
    return () => ipcRenderer.removeListener(channel, sub)
  },
  // app
  health: () => ipcRenderer.invoke('app:health'),
  getVersion: () => ipcRenderer.invoke('app:version'),
  // window: 窗口记忆与控制（better-sqlite3 window_state 回退 electron-store）
  getWindowBounds: () => ipcRenderer.invoke('window:getBounds'),
  saveWindowBounds: (bounds: unknown) => ipcRenderer.invoke('window:saveBounds', bounds),
  windowMinimize: () => ipcRenderer.invoke('window:minimize'),
  windowMaximize: () => ipcRenderer.invoke('window:maximize'),
  windowClose: () => ipcRenderer.invoke('window:close'),
  windowHide: () => ipcRenderer.invoke('window:hide'),
  windowShow: () => ipcRenderer.invoke('window:show'),
  minimize: () => ipcRenderer.invoke('window:minimize'),
  maximize: () => ipcRenderer.invoke('window:maximize'),
  close: () => ipcRenderer.invoke('window:close'),
  hide: () => ipcRenderer.invoke('window:hide'),
  show: () => ipcRenderer.invoke('window:show'),
  // store: 全局状态（better-sqlite3 global_state 优先）
  storeGet: (key: string) => ipcRenderer.invoke('store:get', key),
  storeSet: (key: string, value: unknown) => ipcRenderer.invoke('store:set', { key, value }),
  storeDelete: (key: string) => ipcRenderer.invoke('store:delete', key),
  // notify: 系统通知封装（main 侧 Notification）
  notifyShow: (title: string, body: string) => ipcRenderer.invoke('notify:show', { title, body }),
  notifyPush: (payload: { title: string; body: string; tag?: string }) => ipcRenderer.invoke('notify:push', payload),
  notify: (title: string, body: string) => ipcRenderer.invoke('notify:show', { title, body }),
  // desktop:sync - 窗口+通知同步
  desktopSync: (payload: { bounds?: unknown; notify?: unknown }) => ipcRenderer.invoke('desktop:sync', payload),
  // plan/task/memory 代理
  planCreate: (goalId: number) => ipcRenderer.invoke('plan:create', { goal_id: goalId }),
  taskComplete: (payload: unknown) => ipcRenderer.invoke('task:complete', payload),
  memorySearch: (payload: unknown) => ipcRenderer.invoke('memory:search', payload),
  // workbench 三件套：graph:getState / inspector:open / workbench:sync （P2 W12-14 05-API §4，带 JWT 注入）
  graphGetState: (traceId: string) => ipcRenderer.invoke('graph:getState', { trace_id: traceId }),
  inspectorOpen: (traceId: string) => ipcRenderer.invoke('inspector:open', { trace_id: traceId }),
  workbenchSync: (traceId: string) => ipcRenderer.invoke('workbench:sync', { trace_id: traceId }),
  // 统一 workbench 桥接（供前端 workbench.ts Pinia 一键同步）
  workbench: {
    getGraph: (traceId: string) => ipcRenderer.invoke('graph:getState', { trace_id: traceId }),
    openInspector: (traceId: string) => ipcRenderer.invoke('inspector:open', { trace_id: traceId }),
    sync: (traceId: string) => ipcRenderer.invoke('workbench:sync', { trace_id: traceId }),
    // 流式复用：前端 SSE 直连 /api/v1/plans/stream?trace_id=xxx，此处仅返回 URL 供复用
    streamUrl: (traceId: string) => `http://127.0.0.1:8000/api/v1/plans/stream?trace_id=${encodeURIComponent(traceId)}`,
  },
  openExternal: (url: string) => ipcRenderer.invoke('shell:openExternal', url),
}

contextBridge.exposeInMainWorld('electronBridge', bridge)

declare global {
  interface Window {
    electronBridge: typeof bridge
  }
}
