import type { IpcMain, BrowserWindow } from 'electron'
import { app, shell, Notification } from 'electron'
import { getWindowBounds, saveWindowBounds, getGlobal, setGlobal, deleteGlobal } from './store'
import { showNotification, notifyFromPayload } from './tray'

/**
 * P2 IPC 完整链路：renderer ↔ main ↔ FastAPI sidecar
 * 通道：app:health / app:version / window:* / store:* / notify:* / plan:* / task:* / desktop:sync
 * 与 preload bridge.invoke 对齐，保证前端可直连 /api/v1 同时经 IPC 注入鉴权
 */
export function registerMainIpc(ipcMain: IpcMain, getWindow: () => BrowserWindow | null): void {
  // 健康自检
  ipcMain.handle('app:health', async () => ({
    status: 'ok',
    version: app.getVersion(),
    electron: process.versions.electron,
    node: process.versions.node,
    platform: process.platform,
    notifySupported: Notification.isSupported(),
  }))

  ipcMain.handle('app:version', async () => app.getVersion())

  // 窗口状态：better-sqlite3 + fallback
  ipcMain.handle('window:getBounds', async () => getWindowBounds())
  ipcMain.handle('window:saveBounds', async (_e, bounds) => {
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
  ipcMain.handle('window:show', async () => getWindow()?.show())

  // 通用全局状态（替代 better-sqlite3 初期 global_state 表）
  ipcMain.handle('store:get', async (_e, key: string) => getGlobal(key))
  ipcMain.handle('store:set', async (_e, { key, value }: { key: string; value: unknown }) => {
    setGlobal(key, value)
    return { ok: true }
  })
  ipcMain.handle('store:delete', async (_e, key: string) => {
    deleteGlobal(key)
    return { ok: true }
  })

  // 通知代理：renderer 触发 → main 展示系统通知 + 可选同步 /api/v1/desktop/notify
  ipcMain.handle('notify:show', async (_e, payload: { title: string; body: string }) => {
    showNotification(payload.title, payload.body)
    return { ok: true }
  })
  ipcMain.handle('notify:push', async (_e, payload: { title: string; body: string; tag?: string }) => {
    notifyFromPayload(payload)
    return { ok: true }
  })

  // 桌面同步：窗口bounds + 通知配置（供前端联调示例）
  ipcMain.handle('desktop:sync', async (_e, payload: { bounds?: unknown; notify?: unknown }) => {
    if (payload.bounds) saveWindowBounds(payload.bounds as never)
    if (payload.notify) setGlobal('desktop:notify', payload.notify)
    return { ok: true, bounds: getWindowBounds(), notify: getGlobal('desktop:notify') }
  })

  // Plan / Task / Graph / Inspector 真实代理至 FastAPI，注入 JWT（05-API §4）
  async function _authHeaders(): Promise<Record<string, string>> {
    const token = getGlobal('auth:token') as string | undefined
    return token ? { Authorization: `Bearer ${token}` } : {}
  }
  ipcMain.handle('plan:create', async (_e, payload: { goal_id: number; preferences?: unknown }) => {
    try {
      const headers = { 'Content-Type': 'application/json', ...(await _authHeaders()) }
      const res = await fetch('http://127.0.0.1:8000/api/v1/plans', { method: 'POST', headers, body: JSON.stringify(payload) })
      return await res.json()
    } catch (e) { return { code: 50001, msg: String((e as Error).message), data: null } }
  })
  ipcMain.handle('task:complete', async (_e, payload: { task_id: number; actual_duration: number; completion_rate: number }) => {
    try {
      const headers = { 'Content-Type': 'application/json', ...(await _authHeaders()) }
      const res = await fetch(`http://127.0.0.1:8000/api/v1/tasks/${(payload as { task_id: number }).task_id}/complete`, { method: 'POST', headers, body: JSON.stringify(payload) })
      return await res.json()
    } catch (e) { return { code: 50001, msg: String((e as Error).message), data: null } }
  })
  ipcMain.handle('memory:search', async (_e, payload: { q: string; top_k?: number }) => {
    try {
      const headers = await _authHeaders()
      const qs = new URLSearchParams({ q: payload.q, top_k: String(payload.top_k ?? 5) }).toString()
      const res = await fetch(`http://127.0.0.1:8000/api/v1/memory/search?${qs}`, { headers })
      return await res.json()
    } catch (e) { return { code: 50001, msg: String((e as Error).message), data: null } }
  })
  ipcMain.handle('graph:getState', async (_e, payload: { trace_id: string }) => {
    try {
      const headers = await _authHeaders()
      const res = await fetch(`http://127.0.0.1:8000/api/v1/plans/${encodeURIComponent(payload.trace_id)}/graph`, { headers })
      return await res.json()
    } catch (e) { return { code: 50001, msg: String((e as Error).message), data: null } }
  })
  ipcMain.handle('inspector:open', async (_e, payload: { trace_id: string }) => {
    try {
      const headers = await _authHeaders()
      const res = await fetch(`http://127.0.0.1:8000/api/v1/plans/${encodeURIComponent(payload.trace_id)}/inspector`, { headers })
      return await res.json()
    } catch (e) { return { code: 50001, msg: String((e as Error).message), data: null } }
  })
  ipcMain.handle('workbench:sync', async (_e, payload: { trace_id: string }) => {
    try {
      const headers = await _authHeaders()
      const [graphRes, inspectorRes] = await Promise.all([
        fetch(`http://127.0.0.1:8000/api/v1/plans/${encodeURIComponent(payload.trace_id)}/graph`, { headers }).then(r => r.json()).catch(() => null),
        fetch(`http://127.0.0.1:8000/api/v1/plans/${encodeURIComponent(payload.trace_id)}/inspector`, { headers }).then(r => r.json()).catch(() => null),
      ])
      return { code: 200, msg: 'ok', data: { graph: graphRes?.data ?? null, inspector: inspectorRes?.data ?? null, trace_id: payload.trace_id } }
    } catch (e) { return { code: 50001, msg: String((e as Error).message), data: null } }
  })

  // 外部链接
  ipcMain.handle('shell:openExternal', async (_e, url: string) => {
    await shell.openExternal(url)
    return { ok: true }
  })
}
