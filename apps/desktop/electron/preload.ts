import { contextBridge, ipcRenderer } from 'electron'

export type AgentCommand = 'agent:new-session' | 'agent:focus-composer' | 'agent:toggle-inspector'

const agentCommandChannels: readonly AgentCommand[] = ['agent:new-session', 'agent:focus-composer', 'agent:toggle-inspector']

// P0 通道白名单：堵住任意透传，未知通道直接抛错（只允许已知 app:/window:/store:/notify*/desktop:/plan:/task:/memory:/graph:/inspector:/workbench:/reflection:/shell:openExternal）
const ALLOWED_INVOKE_CHANNELS: ReadonlySet<string> = new Set([
  'app:health',
  'app:version',
  'window:getBounds',
  'window:saveBounds',
  'window:minimize',
  'window:maximize',
  'window:close',
  'window:hide',
  'window:show',
  'store:get',
  'store:set',
  'store:delete',
  'notify:show',
  'notify:push',
  'notify',
  'desktop:sync',
  'desktop:window-state',
  'desktop:config',
  'desktop:notifications',
  'desktop:notify',
  'plan:create',
  'plan:stream',
  'task:complete',
  'memory:search',
  'graph:getState',
  'inspector:open',
  'workbench:sync',
  'workbench:getState',
  'reflection:latest',
  'reflection:week',
  'reflection:run',
  'shell:openExternal',
])

// Main→Renderer 推送白名单：onAgentCommand 相关 + plan:stream 分块 + 通知深链 + 快捷键提示
const ALLOWED_ON_CHANNELS: ReadonlySet<string> = new Set([
  'agent:new-session',
  'agent:focus-composer',
  'agent:toggle-inspector',
  'show-shortcuts',
  'plan:stream:chunk',
  'plan:stream:end',
  'plan:stream:error',
  'notification:click',
])

function assertInvokeChannel(channel: string): void {
  if (!ALLOWED_INVOKE_CHANNELS.has(channel)) {
    throw new Error(`[preload] blocked unknown invoke channel: ${channel}`)
  }
}

function assertOnChannel(channel: string): void {
  if (!ALLOWED_ON_CHANNELS.has(channel)) {
    throw new Error(`[preload] blocked unknown on channel: ${channel}`)
  }
}
const bridge = {
  // 通用（白名单校验后透传）
  invoke: (channel: string, data?: unknown) => {
    assertInvokeChannel(channel)
    return ipcRenderer.invoke(channel, data)
  },
  on: (channel: string, callback: (...args: unknown[]) => void) => {
    assertOnChannel(channel)
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
  // desktop 细粒度直映射（P1：不再只走批量 sync）
  desktopGetWindowState: () => ipcRenderer.invoke('desktop:window-state', { method: 'get' }),
  desktopPutWindowState: (state: unknown) => ipcRenderer.invoke('desktop:window-state', { method: 'put', state }),
  desktopGetConfig: () => ipcRenderer.invoke('desktop:config'),
  desktopGetNotifications: (limit?: number) => ipcRenderer.invoke('desktop:notifications', { limit: limit ?? 10 }),
  desktopNotify: (payload: { title: string; body: string; tag?: string }) => ipcRenderer.invoke('desktop:notify', payload),
  // plan/task/memory 代理
  planCreate: (goalId: number) => ipcRenderer.invoke('plan:create', { goal_id: goalId }),
  // plan:stream SSE 代理：Main 拉后端 SSE 后经 plan:stream:chunk/end/error 分块转发，断线由渲染侧重连
  planStream: (traceId: string, opts?: { ticket?: string; last_event_id?: string }) =>
    ipcRenderer.invoke('plan:stream', { trace_id: traceId, ticket: opts?.ticket, last_event_id: opts?.last_event_id }),
  onPlanStreamChunk: (callback: (payload: unknown) => void) => {
    assertOnChannel('plan:stream:chunk')
    const sub = (_: unknown, payload: unknown) => callback(payload)
    ipcRenderer.on('plan:stream:chunk', sub)
    return () => ipcRenderer.removeListener('plan:stream:chunk', sub)
  },
  onPlanStreamEnd: (callback: (payload: unknown) => void) => {
    assertOnChannel('plan:stream:end')
    const sub = (_: unknown, payload: unknown) => callback(payload)
    ipcRenderer.on('plan:stream:end', sub)
    return () => ipcRenderer.removeListener('plan:stream:end', sub)
  },
  onPlanStreamError: (callback: (payload: unknown) => void) => {
    assertOnChannel('plan:stream:error')
    const sub = (_: unknown, payload: unknown) => callback(payload)
    ipcRenderer.on('plan:stream:error', sub)
    return () => ipcRenderer.removeListener('plan:stream:error', sub)
  },
  // reflection 代理（P0：latest/week/run）
  reflectionLatest: () => ipcRenderer.invoke('reflection:latest'),
  reflectionWeek: (week: string) => ipcRenderer.invoke('reflection:week', { week }),
  reflectionRun: (week?: string) => ipcRenderer.invoke('reflection:run', week ? { week } : {}),
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
  // 通知深链：main 侧 click 聚焦窗口后经 notification:click 推送 tag/trace_id，渲染层决定是否消费
  onNotificationClick: (callback: (payload: { title?: string; tag?: string; trace_id?: string }) => void) => {
    assertOnChannel('notification:click')
    const sub = (_: unknown, payload: { title?: string; tag?: string; trace_id?: string }) => callback(payload)
    ipcRenderer.on('notification:click', sub)
    return () => ipcRenderer.removeListener('notification:click', sub)
  },
  onAgentCommand: (callback: (command: AgentCommand) => void) => {
    const offs = agentCommandChannels.map((channel) => {
      const sub = (_: unknown, command: AgentCommand) => callback(command)
      ipcRenderer.on(channel, sub)
      return () => ipcRenderer.removeListener(channel, sub)
    })
    return () => offs.forEach((off) => off())
  },
}

contextBridge.exposeInMainWorld('electronBridge', bridge)

declare global {
  interface Window {
    electronBridge: typeof bridge
  }
}
