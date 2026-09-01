import type { IpcMain } from 'electron'
import { app, shell, Notification, BrowserWindow } from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'
import Store from 'electron-store'

// 三端统一 PLANNER_API
const BASE = process.env.PLANNER_API || "http://127.0.0.1:8000"

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

function showNotification(title: string, body: string): void {
  if (!Notification.isSupported()) {
    console.log('[notify] not supported', title, body)
    return
  }
  const n = new Notification({ title, body, silent: false, urgency: 'normal' })
  n.on('click', () => {
    const w = BrowserWindow.getAllWindows()[0]
    if (w) {
      if (w.isMinimized()) w.restore()
      w.show()
      w.focus()
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

  // 通知代理：renderer 触发 → main 展示系统通知（Notification 封装）
  ipcMain.handle('notify:show', async (_e, payload: { title: string; body: string }) => {
    showNotification(payload.title, payload.body)
    return { ok: true }
  })
  ipcMain.handle('notify:push', async (_e, payload: { title: string; body: string; tag?: string }) => {
    showNotification(payload.title, payload.body)
    return { ok: true }
  })
  // 兼容别名 notify/desktop:sync
  ipcMain.handle('notify', async (_e, payload: { title: string; body: string }) => {
    showNotification(payload.title, payload.body)
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

  // 外部链接
  ipcMain.handle('shell:openExternal', async (_e, url: string) => {
    await shell.openExternal(url)
    return { ok: true }
  })
}
