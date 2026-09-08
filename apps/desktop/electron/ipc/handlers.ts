import type { IpcMain } from 'electron'
import { app, shell, Notification, BrowserWindow } from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'
import Store from 'electron-store'

// 三端统一 PLANNER_API
const BASE = process.env.PLANNER_API || "http://127.0.0.1:8000"

// P1 shell:openExternal 域名白名单（可配置常量）：仅 https（localhost/127.0.0.1 允许 http），未知域拒绝并记日志
const FRONTEND_HOST = (() => {
  try {
    return new URL(process.env.FRONTEND_URL || 'http://localhost:5173').hostname
  } catch {
    return 'localhost'
  }
})()
const ALLOWED_EXTERNAL_HOSTS: ReadonlySet<string> = new Set([
  'localhost',
  '127.0.0.1',
  FRONTEND_HOST,
  'github.com',
  'docs.github.com',
  'electronjs.org',
  'vitejs.dev',
  'vuejs.org',
  'fastapi.tiangolo.com',
  'langchain.com',
  'docs.python.org',
])
function isAllowedExternalUrl(raw: unknown): boolean {
  if (typeof raw !== 'string' || !raw) return false
  let u: URL
  try {
    u = new URL(raw)
  } catch {
    return false
  }
  const isLocal = u.hostname === 'localhost' || u.hostname === '127.0.0.1'
  if (u.protocol === 'http:') {
    if (!isLocal) return false
  } else if (u.protocol !== 'https:') {
    return false
  }
  if (ALLOWED_EXTERNAL_HOSTS.has(u.hostname)) return true
  // 允许己方前端同 host 不同端口（如 localhost:5173/8000）
  if (u.hostname === FRONTEND_HOST) return true
  return false
}

// P2 W17-18：better-sqlite3 优先 fallback electron-store，窗口三表 + 全局状态 + 托盘通知
// 对齐 src/main/store.ts + src/main/ipc.ts 全量通道：app:health/window:*/store:*/notify/desktop:sync
const uiStore = new Store({ name: 'planner-ui-state' })
const windowStore = new Store<{ windowBounds?: unknown }>({ name: 'planner-window-state' })

type WindowBounds = { x?: number; y?: number; width: number; height: number; isMaximized?: boolean }

function getWindowBounds(): WindowBounds | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    if (existsSync(dbPath)) {
      const db = new Database(dbPath, { readonly: true })
      const row = db.prepare('SELECT x,y,width,height,is_maximized FROM window_state WHERE id=?').get('main') as
        | { x: number | null; y: number | null; width: number; height: number; is_maximized: number | null }
        | undefined
      db.close()
      if (row) return { x: row.x ?? undefined, y: row.y ?? undefined, width: row.width, height: row.height, isMaximized: !!row.is_maximized }
    }
  } catch (e) {
    console.log('[ipc] getWindowBounds fallback', (e as Error).message)
  }
  return (windowStore.get('windowBounds') as WindowBounds | undefined) || null
}

function saveWindowBounds(bounds: WindowBounds): void {
  const now = new Date().toISOString()
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    const db = new Database(dbPath)
    db.prepare(
      `INSERT INTO window_state(id,x,y,width,height,is_maximized,updated_at) VALUES('main',?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET x=excluded.x, y=excluded.y, width=excluded.width, height=excluded.height, is_maximized=excluded.is_maximized, updated_at=excluded.updated_at`,
    ).run(bounds.x ?? null, bounds.y ?? null, bounds.width, bounds.height, bounds.isMaximized ? 1 : 0, now)
    db.close()
    return
  } catch (e) {
    console.log('[ipc] saveWindowBounds fallback', (e as Error).message)
  }
  windowStore.set('windowBounds', bounds as never)
}

function getGlobal(key: string): unknown {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    if (existsSync(dbPath)) {
      const db = new Database(dbPath, { readonly: true })
      const row = db.prepare('SELECT value FROM global_state WHERE key=?').get(key) as { value: string } | undefined
      db.close()
      if (row) return JSON.parse(row.value)
    }
  } catch {}
  return uiStore.get(key)
}

function setGlobal(key: string, value: unknown): void {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    const db = new Database(dbPath)
    db.prepare('INSERT INTO global_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(key, JSON.stringify(value))
    db.close()
    return
  } catch {}
  uiStore.set(key, value as never)
}

function deleteGlobal(key: string): void {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require('better-sqlite3')
    const dbPath = join(app.getPath('userData'), 'planner.db')
    if (existsSync(dbPath)) {
      const db = new Database(dbPath)
      db.prepare('DELETE FROM global_state WHERE key=?').run(key)
      db.close()
    }
  } catch {}
  uiStore.delete(key as never)
}

function showNotification(title: string, body: string, extra?: { tag?: string; trace_id?: string }, getWindow?: () => BrowserWindow | null): void {
  if (!Notification.isSupported()) {
    console.log('[notify] not supported', title, body)
    return
  }
  const n = new Notification({ title, body, silent: false, urgency: 'normal' })
  n.on('click', () => {
    const w = getWindow ? getWindow() : BrowserWindow.getAllWindows()[0]
    if (w) {
      if (w.isMinimized()) w.restore()
      w.show()
      w.focus()
      // 通知深链：聚焦后经 IPC 通知渲染层跳转（tag/trace_id 透传，消费与否由前端决定）
      try {
        w.webContents.send('notification:click', { title, tag: extra?.tag, trace_id: extra?.trace_id })
      } catch (e) {
        console.log('[notify] send notification:click failed', (e as Error).message)
      }
    }
  })
  n.show()
}

export function registerIpcHandlers(ipcMain: IpcMain, getWindow: () => BrowserWindow | null) {
  // app:health - 桌面自检（P2 扩展 notifySupported）
  ipcMain.handle('app:health', async () => {
    return {
      status: 'ok',
      version: app.getVersion(),
      electron: process.versions.electron,
      node: process.versions.node,
      platform: process.platform,
      notifySupported: Notification.isSupported(),
    }
  })

  ipcMain.handle('app:version', async () => app.getVersion())

  // 窗口状态：better-sqlite3 window_state + fallback electron-store
  ipcMain.handle('window:getBounds', async () => getWindowBounds())
  ipcMain.handle('window:saveBounds', async (_e, bounds: WindowBounds) => {
    saveWindowBounds(bounds)
    return { ok: true }
  })
  ipcMain.handle('window:minimize', async () => getWindow()?.minimize())
  ipcMain.handle('window:maximize', async () => {
    const w = getWindow()
    if (!w) return
    if (w.isMaximized()) w.unmaximize()
    else w.maximize()
  })
  ipcMain.handle('window:close', async () => getWindow()?.close())
  ipcMain.handle('window:hide', async () => getWindow()?.hide())
  ipcMain.handle('window:show', async () => {
    const w = getWindow()
    if (!w) return
    if (w.isMinimized()) w.restore()
    w.show()
    w.focus()
  })

  // 通用全局状态：better-sqlite3 global_state 优先
  ipcMain.handle('store:get', async (_e, key: string) => getGlobal(key))
  ipcMain.handle('store:set', async (_e, { key, value }: { key: string; value: unknown }) => {
    setGlobal(key, value)
    return { ok: true }
  })
  ipcMain.handle('store:delete', async (_e, key: string) => {
    deleteGlobal(key)
    return { ok: true }
  })

  // 通知代理：renderer 触发 → main 展示系统通知（Notification 封装，深链 tag/trace_id 透传）
  ipcMain.handle('notify:show', async (_e, payload: { title: string; body: string; tag?: string; trace_id?: string }) => {
    showNotification(payload.title, payload.body, { tag: payload.tag, trace_id: payload.trace_id }, getWindow)
    return { ok: true }
  })
  ipcMain.handle('notify:push', async (_e, payload: { title: string; body: string; tag?: string; trace_id?: string }) => {
    showNotification(payload.title, payload.body, { tag: payload.tag, trace_id: payload.trace_id }, getWindow)
    return { ok: true }
  })
  // 兼容别名 notify/desktop:sync
  ipcMain.handle('notify', async (_e, payload: { title: string; body: string; tag?: string; trace_id?: string }) => {
    showNotification(payload.title, payload.body, { tag: payload.tag, trace_id: payload.trace_id }, getWindow)
    return { ok: true }
  })

  // 桌面同步：窗口 bounds + 通知配置（供前端联调）— 兼容 window/bounds 双键名（M1）+ 云端同步（M7） — 三端统一 PLANNER_API
  ipcMain.handle('desktop:sync', async (_e, payload: { bounds?: WindowBounds; window?: WindowBounds; windowState?: WindowBounds; notify?: unknown }) => {
    const bounds = (payload.window || payload.bounds || payload.windowState) as WindowBounds | undefined
    if (bounds) {
      saveWindowBounds(bounds)
      // 同步到后端 /api/v1/desktop/sync（M7 双写）
      try {
        const token = (getGlobal('auth:token') as string) || ''
        await fetch(`${BASE}/api/v1/desktop/sync`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ window: bounds }),
        })
      } catch {}
    }
    if (payload.notify) {
      setGlobal('desktop:notify', payload.notify)
      try {
        const token = (getGlobal('auth:token') as string) || ''
        await fetch(`${BASE}/api/v1/desktop/sync`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ notify: payload.notify }),
        })
      } catch {}
    }
    return { code: 200, msg: 'ok', data: { bounds: getWindowBounds(), notify: getGlobal('desktop:notify') } }
  })

  // plan/task/memory 代理 — 真实代理到 FastAPI（M2），注入 JWT（M4），统一错误码（M6）
  async function _authHeaders(): Promise<Record<string, string>> {
    const token = getGlobal('auth:token') as string | undefined
    return token ? { Authorization: `Bearer ${token}` } : {}
  }
  ipcMain.handle('plan:create', async (_e, payload: { goal_id: number; preferences?: unknown }) => {
    try {
      const headers = { 'Content-Type': 'application/json', ...(await _authHeaders()) }
      const res = await fetch(`${BASE}/api/v1/plans`, { method: 'POST', headers, body: JSON.stringify(payload) })
      const data = await res.json()
      return data
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('task:complete', async (_e, payload: { task_id: number; actual_duration: number; completion_rate: number; delay_reason?: string }) => {
    try {
      const headers = { 'Content-Type': 'application/json', ...(await _authHeaders()) }
      const res = await fetch(`${BASE}/api/v1/tasks/${(payload as { task_id: number }).task_id}/complete`, { method: 'POST', headers, body: JSON.stringify(payload) })
      const data = await res.json()
      return data
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('memory:search', async (_e, payload: { q: string; top_k?: number; type?: string }) => {
    try {
      const headers = await _authHeaders()
      const qs = new URLSearchParams({ q: (payload as { q: string }).q, top_k: String((payload as { top_k?: number }).top_k ?? 5), ...(payload as { type?: string }).type ? { type: (payload as { type: string }).type! } : {} }).toString()
      const res = await fetch(`${BASE}/api/v1/memory/search?${qs}`, { headers })
      const data = await res.json()
      return data
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })

  // 工作台三件套：graph:getState / inspector:open / workbench:sync （P2 W12-14 + 05-API §4）
  ipcMain.handle('graph:getState', async (_e, payload: { trace_id: string }) => {
    try {
      const headers = await _authHeaders()
      const res = await fetch(`${BASE}/api/v1/plans/${encodeURIComponent(payload.trace_id)}/graph`, { headers })
      const data = await res.json()
      return data
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('inspector:open', async (_e, payload: { trace_id: string }) => {
    try {
      const headers = await _authHeaders()
      const res = await fetch(`${BASE}/api/v1/plans/${encodeURIComponent(payload.trace_id)}/inspector`, { headers })
      const data = await res.json()
      return data
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('workbench:sync', async (_e, payload: { trace_id: string }) => {
    try {
      const headers = await _authHeaders()
      // 聚合三路：SSE 事件回放 + graph + inspector，兼容 cache:workbench/graph 5m
      const [graphRes, inspectorRes] = await Promise.all([
        fetch(`${BASE}/api/v1/plans/${encodeURIComponent(payload.trace_id)}/graph`, { headers }).then(r => r.json()).catch(() => null),
        fetch(`${BASE}/api/v1/plans/${encodeURIComponent(payload.trace_id)}/inspector`, { headers }).then(r => r.json()).catch(() => null),
      ])
      // stream 事件走 cache:workbench:{trace_id}，由前端 SSE 直连复用；此处提供快照兜底
      // 可选落 better-sqlite3 workbench_state 便于离线重放
      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const Database = require('better-sqlite3')
        const dbPath = join(app.getPath('userData'), 'planner.db')
        const db = new Database(dbPath)
        db.exec("PRAGMA busy_timeout=5000;");
        db.exec("PRAGMA journal_mode=WAL;");
        db.prepare(`INSERT INTO workbench_state(trace_id, graph, inspector, updated_at) VALUES(?,?,?,?) ON CONFLICT(trace_id) DO UPDATE SET graph=excluded.graph, inspector=excluded.inspector, updated_at=excluded.updated_at`)
          .run(payload.trace_id, JSON.stringify((graphRes as unknown as Record<string, unknown>)?.['data'] ?? null), JSON.stringify((inspectorRes as unknown as Record<string, unknown>)?.['data'] ?? null), new Date().toISOString())
        db.close()
      } catch {}
      return { code: 200, msg: 'ok', data: { graph: (graphRes as unknown as Record<string, unknown>)?.['data'] ?? null, inspector: (inspectorRes as unknown as Record<string, unknown>)?.['data'] ?? null, trace_id: payload.trace_id } }
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  // 兼容旧命名 workbench:sync 别名 workbench:getState
  ipcMain.handle('workbench:getState', async (_e, payload: { trace_id: string }) => {
    try {
      const headers = await _authHeaders()
      const res = await fetch(`${BASE}/api/v1/plans/${encodeURIComponent(payload.trace_id)}/graph`, { headers })
      const data = await res.json()
      return data
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })

  // P0 plan:stream SSE 代理：Main 拉后端 GET /plans/stream，以 Main→Renderer 分块转发
  // 参数透传 ticket/last_event_id，断线由渲染侧重连（监听 plan:stream:error/end 后重新 invoke）
  ipcMain.handle('plan:stream', async (e, payload: { trace_id: string; ticket?: string; last_event_id?: string }) => {
    const sender = e.sender
    const traceId = payload?.trace_id
    if (!traceId) return { code: 40001, msg: 'trace_id 必填', data: null }
    try {
      const headers = await _authHeaders()
      const qs = new URLSearchParams({ trace_id: traceId })
      if (payload.ticket) qs.set('ticket', payload.ticket)
      if (payload.last_event_id) qs.set('last_event_id', payload.last_event_id)
      const fetchHeaders: Record<string, string> = { Accept: 'text/event-stream', ...headers }
      if (payload.last_event_id) fetchHeaders['Last-Event-ID'] = payload.last_event_id
      const res = await fetch(`${BASE}/api/v1/plans/stream?${qs.toString()}`, { headers: fetchHeaders })
      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => '')
        try { sender.send('plan:stream:error', { trace_id: traceId, status: res.status, body: text.slice(0, 500) }) } catch {}
        return { code: 50001, msg: `stream upstream ${res.status}`, data: null }
      }
      // 后台分块转发，不阻塞 invoke 返回（渲染侧通过 on 接收 chunk/end）
      void (async () => {
        try {
          const reader = res.body!.getReader()
          const decoder = new TextDecoder()
          let buf = ''
          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            buf += decoder.decode(value, { stream: true })
            // 按 SSE 行切分转发，保持原文分块语义
            let idx: number
            while ((idx = buf.indexOf('\n')) >= 0) {
              const line = buf.slice(0, idx + 1)
              buf = buf.slice(idx + 1)
              try { sender.send('plan:stream:chunk', { trace_id: traceId, chunk: line }) } catch { return }
            }
          }
          if (buf) {
            try { sender.send('plan:stream:chunk', { trace_id: traceId, chunk: buf }) } catch {}
          }
          try { sender.send('plan:stream:end', { trace_id: traceId }) } catch {}
        } catch (err) {
          try { sender.send('plan:stream:error', { trace_id: traceId, message: String((err as Error).message) }) } catch {}
        }
      })()
      return { code: 200, msg: 'ok', data: { subscribed: true, trace_id: traceId } }
    } catch (err) {
      try { e.sender.send('plan:stream:error', { trace_id: traceId, message: String((err as Error).message) }) } catch {}
      return { code: 50001, msg: String((err as Error).message), data: null }
    }
  })

  // P0 reflection 代理：latest/week/run（不改后端契约，仅透传）
  ipcMain.handle('reflection:latest', async () => {
    try {
      const headers = await _authHeaders()
      const res = await fetch(`${BASE}/api/v1/reflection/latest`, { headers })
      return await res.json()
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('reflection:week', async (_e, payload: { week: string }) => {
    try {
      const headers = await _authHeaders()
      const qs = new URLSearchParams({ week: payload.week }).toString()
      const res = await fetch(`${BASE}/api/v1/reflection/week?${qs}`, { headers })
      return await res.json()
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('reflection:run', async (_e, payload?: { week?: string }) => {
    try {
      const headers = { 'Content-Type': 'application/json', ...(await _authHeaders()) }
      const qs = payload?.week ? `?week=${encodeURIComponent(payload.week)}` : ''
      const res = await fetch(`${BASE}/api/v1/reflection/run${qs}`, { method: 'POST', headers })
      return await res.json()
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })

  // P1 desktop 细粒度直映射（批量 sync 保留，新增 window-state/config/notifications 单点代理）
  ipcMain.handle('desktop:window-state', async (_e, payload?: { method?: string; state?: WindowBounds }) => {
    try {
      const headers = { 'Content-Type': 'application/json', ...(await _authHeaders()) }
      if (payload?.state || payload?.method === 'put') {
        const state = (payload?.state ?? payload) as WindowBounds
        const res = await fetch(`${BASE}/api/v1/desktop/window-state`, { method: 'PUT', headers, body: JSON.stringify(state) })
        const data = await res.json()
        // 本地同步一份，保证离线可恢复
        try { saveWindowBounds(state) } catch {}
        return data
      }
      const res = await fetch(`${BASE}/api/v1/desktop/window-state`, { headers })
      return await res.json()
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('desktop:config', async () => {
    try {
      const headers = await _authHeaders()
      const res = await fetch(`${BASE}/api/v1/desktop/config`, { headers })
      return await res.json()
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('desktop:notifications', async (_e, payload?: { limit?: number }) => {
    try {
      const headers = await _authHeaders()
      const limit = payload?.limit ?? 10
      const res = await fetch(`${BASE}/api/v1/desktop/notifications?limit=${encodeURIComponent(String(limit))}`, { headers })
      return await res.json()
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })
  ipcMain.handle('desktop:notify', async (_e, payload: { title: string; body: string; tag?: string }) => {
    try {
      const headers = { 'Content-Type': 'application/json', ...(await _authHeaders()) }
      const res = await fetch(`${BASE}/api/v1/desktop/notify`, { method: 'POST', headers, body: JSON.stringify(payload) })
      return await res.json()
    } catch (e) {
      return { code: 50001, msg: String((e as Error).message), data: null }
    }
  })

  // 外部链接（P1：https + 域名白名单，拒绝记日志）
  ipcMain.handle('shell:openExternal', async (_e, url: string) => {
    if (!isAllowedExternalUrl(url)) {
      console.warn(`[shell] blocked openExternal url=${String(url).slice(0, 200)}`)
      return { ok: false, code: 40301, msg: 'blocked by allowlist' }
    }
    await shell.openExternal(url)
    return { ok: true }
  })
}
