import type { IpcMain, BrowserWindow } from 'electron'
import { app } from 'electron'
import Store from 'electron-store'

// better-sqlite3 预留: P0 使用 electron-store 避免原生编译失败 (见总计划书风险预案)
// 后续 W17-18 切 better-sqlite3 存储 automations/global_state/inbox_items
const store = new Store({ name: 'planner-ui-state' })

export function registerIpcHandlers(ipcMain: IpcMain, getWindow: () => BrowserWindow | null) {
  // app:health - 桌面自检
  ipcMain.handle('app:health', async () => {
    return {
      status: 'ok',
      version: app.getVersion(),
      electron: process.versions.electron,
      node: process.versions.node,
      platform: process.platform,
    }
  })

  ipcMain.handle('app:version', async () => app.getVersion())

  // app:store - UI 状态存取 (替代 better-sqlite3 初期)
  ipcMain.handle('store:get', async (_e, key: string) => store.get(key))
  ipcMain.handle('store:set', async (_e, { key, value }: { key: string; value: unknown }) => store.set(key, value as never))
  ipcMain.handle('store:delete', async (_e, key: string) => store.delete(key))

  // plan:create 预留 (P0 stub, W3-8 接 FastAPI)
  ipcMain.handle('plan:create', async (_e, payload: { goal_id: number }) => {
    // Dev 代理: 转发到 FastAPI /api/v1/plans (renderer 也可直连，此处演示 IPC 代理注入 Authorization)
    // P0 仅回显，证明 IPC 链路
    return { trace_id: `stub-${Date.now()}`, goal_id: payload.goal_id, tasks: [], mentor_msg: 'P0 stub: 后续接 LangGraph' }
  })

  ipcMain.handle('task:complete', async (_e, payload: unknown) => {
    return { ok: true, payload, note: 'P0 stub' }
  })

  ipcMain.handle('memory:search', async (_e, payload: unknown) => {
    return { items: [], payload, note: 'P0 stub, W12 pgvector' }
  })

  // window control
  ipcMain.handle('window:minimize', async () => getWindow()?.minimize())
  ipcMain.handle('window:maximize', async () => {
    const w = getWindow()
    if (w?.isMaximized()) w.unmaximize()
    else w?.maximize()
  })
  ipcMain.handle('window:close', async () => getWindow()?.close())
}
